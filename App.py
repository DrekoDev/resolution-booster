import streamlit as st
import requests
import base64
import pandas as pd
import os
from datetime import datetime
import time
from PIL import Image
import io

# Configuration de la page
st.set_page_config(
    page_title="Amélioration d'images",
    page_icon="🖼️",
    layout="wide"
)

# Constantes
API_URL = st.secrets["API_URL"]
AIRTABLE_TOKEN = st.secrets["AIRTABLE_TOKEN"]
AUTH_BASE_ID = st.secrets["AUTH_BASE_ID"]
LOGS_BASE_ID = st.secrets["LOGS_BASE_ID"]
TABLE_NAME = st.secrets["TABLE_NAME"]

class AirtableClient:
    def __init__(self, token, base_id, table_name):
        self.token = token
        self.base_id = base_id
        self.table_name = table_name
        self.base_url = f"https://api.airtable.com/v0/{base_id}/{table_name}"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    
    def get_records(self, filter_formula=None):
        """Récupérer les enregistrements d'une table"""
        url = self.base_url
        params = {}
        if filter_formula:
            params["filterByFormula"] = filter_formula
        
        try:
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json().get("records", [])
        except requests.exceptions.RequestException as e:
            st.error(f"Erreur lors de la récupération des données: {e}")
            return []
    
    def create_record(self, fields):
        """Créer un nouvel enregistrement"""
        url = self.base_url
        data = {"fields": fields}
        
        try:
            response = requests.post(url, headers=self.headers, json=data)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            st.error(f"Erreur lors de la création de l'enregistrement: {e}")
            return None
    
    def update_record(self, record_id, fields):
        """Mettre à jour un enregistrement existant"""
        url = f"{self.base_url}/{record_id}"
        data = {"fields": fields}
        
        try:
            response = requests.patch(url, headers=self.headers, json=data)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            st.error(f"Erreur lors de la mise à jour: {e}")
            return None

def initialize_auth_client():
    """Initialiser le client Airtable pour l'authentification"""
    return AirtableClient(AIRTABLE_TOKEN, AUTH_BASE_ID, TABLE_NAME)

def initialize_logs_client():
    """Initialiser le client Airtable pour les logs"""
    return AirtableClient(AIRTABLE_TOKEN, LOGS_BASE_ID, TABLE_NAME)

def check_api_key_credits(api_key):
    """Vérifier les crédits restants pour une clé API"""
    client = initialize_auth_client()
    
    # Rechercher la clé API dans Airtable
    filter_formula = f"{{API_KEY}} = '{api_key}'"
    records = client.get_records(filter_formula)
    
    if not records:
        return None, "Clé API non trouvée"
    
    record = records[0]
    fields = record["fields"]
    used = fields.get("Used_credits", 0)
    allowed = fields.get("Allowed_credits", 0)
    remaining = allowed - used
    
    if remaining <= 0:
        return False, f"Plus de crédits restants (utilisés: {used}/{allowed})"
    
    return True, f"{remaining} crédits restants (utilisés: {used}/{allowed})"

def update_credits(api_key, increment=1):
    """Incrémenter les crédits utilisés d'une clé API"""
    client = initialize_auth_client()
    
    # Rechercher la clé API
    filter_formula = f"{{API_KEY}} = '{api_key}'"
    records = client.get_records(filter_formula)
    
    if records:
        record = records[0]
        current_used = record["fields"].get("Used_credits", 0)
        new_used = current_used + increment
        
        # Mettre à jour l'enregistrement
        client.update_record(
            record["id"], 
            {"Used_credits": new_used}
        )

def log_api_call(api_key, status, original_size=None, output_size=None,
                scale=None, format_type=None, processing_time=None, error_message=None):
    """Enregistrer un appel API dans les logs Airtable"""
    client = initialize_logs_client()
    
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "api_key": api_key,
        "status": status,
        "original_size": str(original_size) if original_size else None,
        "output_size": str(output_size) if output_size else None,
        "scale": scale,
        "format": format_type,
        "processing_time": processing_time,
        "error_message": error_message
    }
    
    client.create_record(log_entry)

def enhance_image(image_data, api_key, scale=4, format_type="JPEG"):
    """Appeler l'API pour améliorer une image"""
    start_time = time.time()
    
    try:
        # Encoder l'image en base64
        image_b64 = base64.b64encode(image_data).decode()
        
        # Préparer la requête
        payload = {
            "image": image_b64,
            "scale": scale,
            "format": format_type
        }
        
        # Faire l'appel API
        response = requests.post(API_URL, json=payload, timeout=300)
        processing_time = round(time.time() - start_time, 2)
        
        if response.status_code == 200:
            result = response.json()
            if result.get("success"):
                # Décoder l'image de sortie
                output_data = base64.b64decode(result["output_image"])
                
                # Log du succès
                log_api_call(
                    api_key=api_key,
                    status="success",
                    original_size=result.get("original_size"),
                    output_size=result.get("output_size"),
                    scale=scale,
                    format_type=format_type,
                    processing_time=processing_time
                )
                
                # Décrémenter les crédits
                update_credits(api_key)
                
                return True, output_data, result
            else:
                error_msg = result.get("error", "Erreur inconnue")
                log_api_call(
                    api_key=api_key,
                    status="api_error",
                    scale=scale,
                    format_type=format_type,
                    processing_time=processing_time,
                    error_message=error_msg
                )
                return False, None, {"error": error_msg}
        else:
            error_msg = f"HTTP {response.status_code}: {response.text}"
            log_api_call(
                api_key=api_key,
                status="http_error",
                scale=scale,
                format_type=format_type,
                processing_time=processing_time,
                error_message=error_msg
            )
            return False, None, {"error": error_msg}
            
    except Exception as e:
        processing_time = round(time.time() - start_time, 2)
        error_msg = str(e)
        log_api_call(
            api_key=api_key,
            status="exception",
            scale=scale,
            format_type=format_type,
            processing_time=processing_time,
            error_message=error_msg
        )
        return False, None, {"error": error_msg}

def get_correct_filename(original_filename, scale, format_type):
    """Génère le nom de fichier correct avec la bonne extension"""
    # Extraire le nom sans extension
    base_name = os.path.splitext(original_filename)[0]
    # Définir la bonne extension (seulement JPEG ou PNG disponibles)
    extension = "jpg" if format_type == "JPEG" else "png"
    # Construire le nouveau nom
    return f"{scale}x_{base_name}.{extension}"

def main():
    """Interface principale Streamlit"""
    st.title("🖼️ Amélioration d'images IA")
    st.markdown("*Augmentez la résolution et la qualité de vos images*")
    st.markdown("---")
    
    # Section configuration au-dessus des colonnes
    st.header("⚙️ Configuration")
    
    # Saisie de la clé API par le client
    api_key = st.text_input("🔑 Clé API", type="password", help="Entrez votre clé API personnelle")
    
    if not api_key:
        st.warning("⚠️ Veuillez entrer votre clé API pour continuer")
        return
    
    # Vérifier les crédits seulement si aucune image n'a été traitée avec succès
    if not st.session_state.get('image_processed', False):
        credits_ok, credits_msg = check_api_key_credits(api_key)
        if credits_ok:
            st.success(f"✅ {credits_msg}")
        elif credits_ok is False:
            st.error(f"❌ {credits_msg}")
            return
        else:
            st.error(f"❌ {credits_msg}")
            return
    else:
        # Si une image a été traitée, afficher juste un message informatif sur les crédits
        credits_ok, credits_msg = check_api_key_credits(api_key)
        if credits_ok is False:
            st.warning(f"⚠️ {credits_msg} - Vous pouvez encore voir votre dernière image générée ci-dessous")
        elif credits_ok:
            st.success(f"✅ {credits_msg}")
        else:
            st.info("ℹ️ Statut des crédits non disponible")
    
    # Upload de l'image
    uploaded_file = st.file_uploader(
        "Choisir une image",
        type=["jpg", "jpeg", "png"],
        help="Formats supportés: JPG, PNG"
    )
    
    if uploaded_file is None:
        st.info("📁 Veuillez sélectionner une image pour commencer")
        return
    
    # Paramètres
    col_param1, col_param2 = st.columns(2)
    
    with col_param1:
        scale = st.selectbox("Facteur d'agrandissement", [2, 4, 8], index=1)
    
    with col_param2:
        format_type = st.selectbox("Format de sortie", ["JPEG", "PNG"], index=0)
    
    # Information sur le résultat attendu
    image = Image.open(uploaded_file)
    new_width = image.size[0] * scale
    new_height = image.size[1] * scale
    st.info(f"📐 Taille actuelle: {image.size[0]}x{image.size[1]} → Nouvelle taille: {new_width}x{new_height} pixels")
    
    st.markdown("---")
    
    # Interface principale - Images côte à côte
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.header("📤 Image d'origine")
        # Afficher l'image originale
        st.image(image, caption=f"Image originale ({image.size[0]}x{image.size[1]})")
    
    with col2:
        st.header("📥 Image améliorée")
        
        # Utiliser session state pour gérer l'état du traitement
        if 'image_processed' not in st.session_state:
            st.session_state.image_processed = False
            st.session_state.output_data = None
            st.session_state.result = None
            st.session_state.processing_time = None
        
        # Réinitialiser si nouvelle image uploadée
        if uploaded_file and hasattr(st.session_state, 'last_uploaded_file'):
            if st.session_state.last_uploaded_file != uploaded_file.name:
                st.session_state.image_processed = False
                st.session_state.output_data = None
                st.session_state.result = None
                st.session_state.processing_time = None
        
        if uploaded_file:
            st.session_state.last_uploaded_file = uploaded_file.name
        
        # Afficher le bouton seulement si pas encore traité
        if not st.session_state.image_processed:
            if st.button("✨ Améliorer l'image", type="primary"):
                with st.spinner("Traitement en cours..."):
                    # Démarrer le chronomètre
                    start_time = time.time()
                    
                    # Convertir l'image en bytes
                    img_bytes = uploaded_file.getvalue()
                    
                    # Appeler l'API
                    success, output_data, result = enhance_image(
                        img_bytes, api_key, scale, format_type
                    )
                    
                    # Calculer le temps de traitement
                    processing_time = round(time.time() - start_time, 2)
                    
                    if success:
                        # Sauvegarder dans session state
                        st.session_state.image_processed = True
                        st.session_state.output_data = output_data
                        st.session_state.result = result
                        st.session_state.processing_time = processing_time
                        st.rerun()
                    else:
                        st.error(f"❌ Erreur lors du traitement: {result.get('error', 'Erreur inconnue')}")
        else:
            # Afficher l'image améliorée si déjà traitée
            output_image = Image.open(io.BytesIO(st.session_state.output_data))
            st.image(
                output_image,
                caption=f"Image améliorée ({st.session_state.result.get('output_size', 'N/A')})"
            )
            
            # Générer le nom de fichier avec la bonne extension
            filename = get_correct_filename(uploaded_file.name, scale, format_type)
            
            # Bouton de téléchargement
            st.download_button(
                label="💾 Télécharger l'image améliorée",
                data=st.session_state.output_data,
                file_name=filename,
                mime=f"image/{format_type.lower()}"
            )
    
    # Section résumé de l'opération si image traitée
    if st.session_state.get('image_processed', False):
        st.markdown("---")
        st.header("📊 Résumé de l'opération")
        
        col_info1, col_info2 = st.columns(2)
        
        with col_info1:
            st.markdown(f"**Taille originale:** {st.session_state.result.get('original_size', 'N/A')}")
            st.markdown(f"**Facteur d'agrandissement:** {scale}x")
        
        with col_info2:
            st.markdown(f"**Nouvelle taille:** {st.session_state.result.get('output_size', 'N/A')}")
            st.markdown(f"**Temps de traitement:** {st.session_state.processing_time}s")

if __name__ == "__main__":
    main()