#!/bin/bash
mkdir -p ~/.streamlit/
echo "
[server]
headless = true
enableCORS=false
enableXsrfProtection=false
"

streamlit run main.py