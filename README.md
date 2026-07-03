# Cridos-Reddit-Upvote-Bot
Cridos Reddit Upvote Bot Automation software for gaining visibility on Reddit social media platform

HERE BELOW ARE THE STEPS TO LUNCH THE AUTOMATION SOFTWARE ON YOUR VPS (VIRTUAL PRIVATE SERVER)

[GITHUB LINK TO PPROJECT FULL SOURCE CODE:](https://github.com/jokonoko/Cridos-Reddit-Upvote-Bot)

STEP 1 : After you have downloaded the source code in a zipped file you must unzip and extract the main folder to your pc (Cridos-Reddit-Upvote-Bot-main) FOLDER


STEP 2 : You must have your Rotating mobile proxy credentails and your VPS server ready


STEP 3 : Head to the env.env file in (Cridos-Reddit-Upvote-Bot-main\CridosRedditUpvoteBot\Upvotebot) FOLDER to configure your rotating mobile proxy credentials and don't forget to also configure the Rotation link as well then save the file and close


STEP 4 : Now we must connect to our VPS server, update it, download docker and create a directory on the vps server where our project will live

step 4.1 : Connect to Your VPS

  On Windows, open PowerShell or Command Prompt (powershell prefered):

  ssh root@YOUR_VPS_IP

  Type yes when asked about fingerprint, then enter your VPS password you have set.

step 4.2 : Update the System

  apt update && apt upgrade -y

  This may take a few minutes.

step 4.3 : Install Docker

  curl -fsSL https://get.docker.com | sh

  VERIFY it installed:
  docker --version

step 4.4 : Install Docker Compose

  apt install docker-compose-plugin -y

  VERIFY:
  docker compose version

step 4.5 : Create Project Directory

  mkdir -p ~/CridosRedditUpvoteBotVPS
  cd ~/CridosRedditUpvoteBotVPS



STEP 5 : now we must Upload our source code from our local machine to the VPS directory we made 

step 5.1 : Upload Your Project Files

  Open a NEW PowerShell window on your local Windows machine (keep the VPS POWERSHELL open):

  scp -r C:\Users\Cridos-Reddit-Upvote-Bot-main\CridosRedditUpvoteBot\Upvotebot\* root@YOUR_VPS_IP:~/CridosRedditUpvoteBotVPS/

  Enter your VPS password when prompted. Wait for all files to upload.

step 5.2 : Go Back to the VPS POWERSHELL and Verify Files have uploaded compeletly

  In your VPS POWERSHELL:
  cd ~/Upvotebot
  ls -la 
  You should see files like docker-compose.yml, main.py, requirements.txt, etc.



STEP 6 : Now after we have verified our Full source code has been uploaded to our VPS we can move on to continue setting it up we will Build docker Images, start all services, check everything is running, open Firewall port, and then finally Access the dashboard (web page)

step 6.1 : Build Docker Images

  docker compose build

  This will take 5-10 minutes the first time (downloads dependencies, installs Playwright
  browser).

step 6.2 : Start All Services

  docker compose up -d

step 6.3 : Check Everything is Running

  docker compose ps

  You should see 4 services all showing "Up":
  NAME                    STATUS
  CridosRedditUpvoteBotVPS-redis-1      Up
  CridosRedditUpvoteBotVPS-web-1        Up (healthy)
  CridosRedditUpvoteBotVPS-worker-1     Up
  CridosRedditUpvoteBotVPS-scheduler-1  Up (currently disabled so it won't show up)

Step 6.4 : Open Firewall Port

  ufw allow 22
  ufw allow 8000
  ufw enable

step 6.5 : Access the Dashboard

  Open your browser and go to:
  http://YOUR_VPS_IP:8000

  Login with:
  - Username: admin
  - Password: admin (you can change password in the env.env file)


