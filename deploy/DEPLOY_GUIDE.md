# Celo Trader — AWS Deployment Guide

## What you'll end up with
- EC2 t2.micro (free tier) running Ubuntu 22.04
- Trading bot auto-starts at boot, restarts if it crashes
- Streamlit dashboard at `http://YOUR_IP:8501` from any browser
- One command to push code updates from your Mac

---

## Step 1 — Create AWS Account

1. Go to **https://aws.amazon.com** → click **Create an AWS Account**
2. Enter email, choose account name (e.g. "Celo Trader")
3. Select **Free** support plan
4. Add a credit card (won't be charged while on free tier)
5. Verify your phone number
6. Log in to the **AWS Console** at console.aws.amazon.com

---

## Step 2 — Launch an EC2 Instance

1. In the AWS Console search bar, type **EC2** and click it
2. Click **Launch Instance** (orange button)
3. Fill in:
   - **Name**: `celo-trader`
   - **AMI**: Ubuntu Server 22.04 LTS *(select this — it's free tier eligible)*
   - **Instance type**: `t2.micro` *(free tier — 750 hrs/month free for 12 months)*
   - **Key pair**: Click **Create new key pair**
     - Name: `celo_trader`
     - Type: RSA
     - Format: `.pem`
     - Click **Create key pair** — it auto-downloads `celo_trader.pem`
   - **Network settings** → **Edit** → Add these inbound rules:
     - SSH (port 22) — Source: My IP
     - Custom TCP (port 8501) — Source: Anywhere IPv4 *(for Streamlit)*
   - **Storage**: 20 GB gp3 *(increase from default 8 GB)*
4. Click **Launch Instance**

Move your key to a safe place and lock it down:
```bash
mv ~/Downloads/celo_trader.pem ~/.ssh/
chmod 400 ~/.ssh/celo_trader.pem
```

---

## Step 3 — Allocate an Elastic IP (stable address)

Without this, your EC2 IP changes every time it restarts.

1. In EC2 Console → left sidebar → **Elastic IPs**
2. Click **Allocate Elastic IP address** → **Allocate**
3. Select the new IP → **Actions** → **Associate Elastic IP address**
4. Select your `celo-trader` instance → **Associate**
5. Copy the IP address — this is your permanent server address

---

## Step 4 — SSH into the Server

```bash
ssh -i ~/.ssh/celo_trader.pem ubuntu@YOUR_ELASTIC_IP
```

---

## Step 5 — Bootstrap the Server

Upload the setup script and run it:

```bash
# From your Mac (in the celo_trader directory)
scp -i ~/.ssh/celo_trader.pem deploy/setup_ec2.sh ec2-user@3.148.153.141:~

# On the server
chmod +x setup_ec2.sh
sudo ./setup_ec2.sh
```

---

## Step 6 — Upload Your Code

Back on your Mac, run:

```bash
cd /Applications/celo_trader
chmod +x deploy/sync_to_ec2.sh
./deploy/sync_to_ec2.sh YOUR_ELASTIC_IP
```

This syncs all Python files (not the database, not .env — those stay separate).

---

## Step 7 — Create the .env File on EC2

```bash
# SSH into the server
ssh -i ~/.ssh/celo_trader.pem ubuntu@YOUR_ELASTIC_IP

# Create the env file
sudo nano /opt/celo_trader/.env
```

Paste the contents of `deploy/env_template.txt` and fill in your real API keys. Save with `Ctrl+O`, `Enter`, `Ctrl+X`.

Lock down the file:
```bash
sudo chown celo:celo /opt/celo_trader/.env
sudo chmod 600 /opt/celo_trader/.env
```

---

## Step 8 — Start the Bot and Dashboard

```bash
# SSH into the server
ssh -i ~/.ssh/celo_trader.pem ubuntu@YOUR_ELASTIC_IP

# Start both services
sudo systemctl start celo-bot
sudo systemctl start celo-dashboard

# Check they're running
sudo systemctl status celo-bot
sudo systemctl status celo-dashboard
```

Open your browser: **http://YOUR_ELASTIC_IP:8501**

---

## Day-to-Day Commands

| Task | Command (on server) |
|------|-------------------|
| Push code updates | `./deploy/sync_to_ec2.sh YOUR_IP` *(from Mac)* |
| View bot logs | `sudo journalctl -u celo-bot -f` |
| View dashboard logs | `sudo journalctl -u celo-dashboard -f` |
| Restart bot | `sudo systemctl restart celo-bot` |
| Stop everything | `sudo systemctl stop celo-bot celo-dashboard` |
| Check status | `sudo systemctl status celo-bot celo-dashboard` |

---

## Cost

- **t2.micro**: Free for 12 months (750 hrs/month), then ~$8.50/month
- **EBS 20GB**: Free for 12 months (30GB free tier), then ~$1.60/month  
- **Elastic IP**: Free while the instance is running, $0.005/hr if you stop the instance
- **Data transfer**: First 100GB outbound free

**Total after free tier**: ~$10–12/month
