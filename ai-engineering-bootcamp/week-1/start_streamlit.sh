#!/bin/sh
# Start Streamlit on Render (bind to $PORT and all interfaces)
streamlit run demo_page.py --server.port $PORT --server.address 0.0.0.0
