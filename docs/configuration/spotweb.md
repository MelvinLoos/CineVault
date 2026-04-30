# Spotweb Integration

Spotweb is a Dutch Usenet indexer that consumes spots and headers from Usenet and exposes them as a Newznab-compatible feed. Because SQLite cannot scale to the millions of headers typically found in Dutch Usenet spots, this stack ships with a dedicated **MariaDB** container specifically for Spotweb.

Ansible has already provisioned the necessary containers and networking, and it has automatically removed the dummy database settings file to ensure a clean start. You only need to complete the following manual UI-side steps to finalize the setup.

## Step 1 — Run the Spotweb installer

1. Open `http://<host-ip>:8085/install.php` in your web browser.
2. Click through the initial installer screens.
3. On the **Database settings** screen, you MUST enter the values that match your `.env` configuration:
    - **DB Type**: **MySQL**
    - **DB Host**: **spotweb-db**
    - **DB Name**: **spotweb** (or the value of `SPOTWEB_DB_NAME`)
    - **DB User**: **spotweb** (or the value of `SPOTWEB_DB_USER`)
    - **DB Password**: The value of `SPOTWEB_DB_PASSWORD` from your `.env` file.

!!! warning "Important: DB Hostname"
    The **DB Host** must be set to the Docker DNS name **spotweb-db**, NOT `localhost` or an IP address. This is because both the Spotweb and MariaDB containers share the `acquisition_net` Docker network.

## Step 2 — Enter Usenet Provider details

1. Once the installer finishes or once logged into Spotweb, navigate to **Settings** -> **Server Settings**.
2. Enter your Usenet provider details:
    - **Hostname**: Your provider's NNTP address (e.g., `news.provider.com`).
    - **Port**: Usually `563` (for SSL) or `119`.
    - **SSL**: Check this if using an SSL port.
    - **Username**: Your Usenet account username.
    - **Password**: Your Usenet account password.
3. **Connections**: It is recommended to set this between **8–20 connections**, depending on your provider plan.

## Step 3 — Retrieve the Spotweb API key

1. Click on the **user avatar / profile icon** in the top right corner of the Spotweb UI.
2. Navigate to **User Profile** (or **My Profile**).
3. Locate the **API Key** field and **copy** its value. You will need this for Prowlarr.

## Step 4 — Add Spotweb to Prowlarr

1. Open **Prowlarr** and navigate to **Indexers** -> **Add Indexer**.
2. Search for and select the **Spotweb** (Newznab generic) entry.
3. Configure the indexer with the following settings:
    - **Base URL**: `http://spotweb:80` (Use the internal Docker DNS name; do NOT use the public URL or host IP).
    - **API Key**: The value you copied in **Step 3**.
4. Click **Test** to verify the connection.
5. Click **Save**.

Prowlarr will now automatically sync the Spotweb indexer to your connected applications like Radarr and Sonarr.

## Troubleshooting

- **`/install.php` returns a blank page or "already installed"**: Confirm that Ansible successfully removed `dbsettings.inc.php`. You can check the container volume for this file.
- **Spotweb cannot reach the Database**: Verify that both the `spotweb` and `spotweb-db` containers are running and attached to the `acquisition_net` network. Double-check that the credentials in `.env` match those entered in the installer.
- **Prowlarr test fails**: Ensure that the **Base URL** in Prowlarr uses the container name `spotweb` rather than `localhost` or the host IP, as they communicate over the internal Docker network.
