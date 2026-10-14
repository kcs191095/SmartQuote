import streamlit as st
from streamlit_lottie import st_lottie
import requests

def load_lottieurl(url):
    r = requests.get(url)
    if r.status_code != 200:
        return None
    return r.json()

st.title("Hola Mundo 👋")

# Animación de ejemplo desde Lottie
lottie_hello = load_lottieurl("https://assets5.lottiefiles.com/packages/lf20_V9t630.json")
if lottie_hello:
    st_lottie(lottie_hello, height=300)

st.balloons()

# --- Texto nuevo que agregamos abajo ---
st.subheader("SmartQuote")
st.write("Trabajando en la aplicación del reto.")
