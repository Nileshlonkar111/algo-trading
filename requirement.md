@v1.1.py is algo script in py which is being used. it ahs KiteConnect library use to communicate with broking app. major challenge here is this script has api key and access token, access token we have to generate everyday. 

Curent process to get access token

# get_access_token.py
from kiteconnect import KiteConnect

API_KEY = "your_api_key_here"
API_SECRET = "your_api_secret_here"

kite = KiteConnect(api_key=API_KEY)

# STEP 1: Print login URL
print("Login URL:", kite.login_url())

# After login, get request_token and enter below
request_token = input("Enter request token here: ").strip()

# STEP 2: Generate access token
try:
    session_data = kite.generate_session(request_token, api_secret=API_SECRET)
    access_token = session_data["access_token"]

    print("\n========== ACCESS TOKEN ==========")
    print(access_token)
    print("==================================")
except Exception as e:
    print("Error:", e)

6. How to Use the Script
Step 1 — Run the script
python get_access_token.py


It prints:

Login URL: https://kite.zerodha.com/connect/login?v=3&api_key=xxxx

Step 2 — Open the login URL

Login using:

Zerodha ID

Password

PIN/OTP

Step 3 — After login

You are redirected to your redirect URL like:

https://127.0.0.1/?request_token=ABCD1234


Copy only:

ABCD1234

ABOVE MANUAL PART SHOULD COME UNDER PART OF LOGIN 


------------------------------------------------------------------------

After this we will be able to run the scrip @v1.1.py. Now I want to convert this script into full fledg algo web app with the same logic and same broker. Want to keep the backend in python only. Dashboard must be there which monitor evrything which currently on the script only. Remove paper trading logic. Need complete production ready app.

LIMITATION : 
have only one EC2 instance of free tier for deployment.
Need simple  but effective app
Logic should remain unchanged