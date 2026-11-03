# Turning on "Sign in with Google"

The app works without this: people sign up with email and password. These steps add the
**Continue with Google** button to the login and sign-up pages. It takes about 10 minutes and
is free. You need a Google account.

## 1. Create a Google Cloud project

1. Go to https://console.cloud.google.com/ and sign in.
2. Click the project picker at the top of the page, then **New project**.
3. Name it something like `TechCare portal demo`, then click **Create** and wait for the
   notification. Make sure the new project is selected in the picker.

## 2. Set up the consent screen

This is the screen people see when Google asks "Allow TechCare Services to see your email
address?".

1. In the search bar, type **Google Auth Platform** and open it. Click **Get started**.
2. **App information:** app name `TechCare Services (demo)`, and choose your email as the
   user support email. Click **Next**.
3. **Audience:** choose **External**. Click **Next**.
4. **Contact information:** your email. Click **Next**, tick the agreement, then **Create**.
5. Open **Audience** in the left menu. Under **Test users**, click **Add users** and add the
   Gmail address(es) you'll test with. While the app is in *Testing* mode, **only these
   people can sign in**. That's fine for a demo, and nobody else can use your app.

The app only asks for the basic `openid`, `email` and `profile` scopes, so Google doesn't
need to review it.

## 3. Create the OAuth client

1. Open **Clients** in the left menu, then click **Create client**.
2. **Application type:** *Web application*. **Name:** `TechCare local`.
3. Under **Authorized JavaScript origins**, add both:
   - `http://127.0.0.1:8000`
   - `http://localhost:8000`
4. Under **Authorized redirect URIs**, add both:
   - `http://127.0.0.1:8000/accounts/google/login/callback/`
   - `http://localhost:8000/accounts/google/login/callback/`
5. Click **Create**. A box shows the **Client ID** and **Client secret**. Copy both (you can
   come back to the client later to see them again).

## 4. Give the keys to the app

1. Open the `.env` file in the project folder (create it from `.env.example` if you haven't).
2. Fill in the two lines:

   ```text
   GOOGLE_CLIENT_ID=1234567890-abc...apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=GOCSPX-...
   ```

3. Stop the server (Ctrl+C) and start it again with `python manage.py runserver`. Settings
   are read once at start-up.
4. Open http://127.0.0.1:8000/accounts/login/. The **Continue with Google** button is there.
   Click it, pick one of your test users and allow access. You land in the portal as a new
   home customer.

## Keep the secret secret

- `.env` is in `.gitignore`, so git won't commit it. Never paste the secret into code, a
  README, an issue or a chat.
- If the secret ever leaks, open the client in Google Cloud, **add a new secret**, update
  `.env`, then delete the old secret.
- The demo runs on `http://` locally. A real deployment must use `https://`, and its own
  address added to the origins and redirect URIs.

## If something goes wrong

| What you see | Why, and the fix |
|---|---|
| No Google button | One of the two `.env` values is empty, or the server wasn't restarted |
| `Error 400: redirect_uri_mismatch` | The address in your browser doesn't match a redirect URI exactly. Use the same host you registered (`127.0.0.1` vs `localhost`), with the port and the trailing `/` |
| `Access blocked: ... has not completed the Google verification process` | The Google account isn't in **Test users** (step 2.5) |
| Signed in with Google but asked to sign up | Normal the first time: allauth may ask you to confirm details before creating the account |
| An account with that email already exists | The address was already used for an email sign-up. Log in with the password instead. allauth doesn't join the two accounts automatically, which stops someone taking over an account through a Google account with the same address |
