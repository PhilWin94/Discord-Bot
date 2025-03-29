# Discord AI Assistant Bot

## Description

This is a simple Discord bot that uses the OpenAI Assistants API to provide conversational AI capabilities. It interacts with users via Direct Messages (DMs) or when mentioned in server channels. The bot maintains separate conversation contexts for each user, remembering past interactions within that user's specific conversation thread using OpenAI's Threads feature and storing the user-to-thread mapping locally in a JSON file.

## Features

* Interacts with users via Direct Messages (DMs).
* Responds when mentioned in server channels.
* Uses OpenAI Assistants API for responses.
* Maintains persistent conversation history per user using OpenAI Threads.
* Stores the mapping between Discord User IDs and OpenAI Thread IDs locally in `user_threads_data.json`.
* Configuration via `.env` file for API keys and IDs.

## Prerequisites

Before you begin, ensure you have the following:

* **Python 3.8+** installed.
* A **Discord Bot Token**. You can get this from the [Discord Developer Portal](https://discord.com/developers/applications). Your bot will need the `MESSAGE CONTENT`, `SERVER MEMBERS`, and `DIRECT MESSAGES` Privileged Gateway Intents enabled.
* An **OpenAI API Key**. Get one from the [OpenAI Platform](https://platform.openai.com/api-keys).
* An **OpenAI Assistant ID**. You need to create an Assistant via the [OpenAI Assistants Playground](https://platform.openai.com/assistants) or API and get its ID (looks like `asst_...`).

## Setup

1.  **Download or Clone the Code:**
    * If using Git: `git clone <your-repo-url>`
    * Otherwise: Download the code files (`your_bot_script_name.py`, etc.) into a dedicated folder on your PC.

2.  **Navigate to the Project Directory:**
    ```bash
    cd path/to/your/bot/folder
    ```

3.  **Create `requirements.txt`:**
    Create a file named `requirements.txt` in the project directory with the following content:

    ```txt
    # requirements.txt
    discord.py
    openai>=1.0.0 # Specify version if needed
    python-dotenv
    ```

4.  **Install Dependencies:**
    Open your terminal or command prompt in the project directory and run:
    ```bash
    pip install -r requirements.txt
    ```

5.  **Create the `.env` File:**
    Create a file named exactly `.env` in the *same directory* as your bot script. Add your API keys and Assistant ID to this file like so:

    ```dotenv
    # .env file - Keep this file secure and DO NOT commit it to Git!
    DISCORD_BOT_TOKEN="YOUR_DISCORD_BOT_TOKEN_HERE"
    OPENAI_API_KEY="YOUR_OPENAI_API_KEY_HERE"
    ASSISTANT_ID="YOUR_OPENAI_ASSISTANT_ID_HERE"
    ```
    Replace the placeholder text with your actual credentials.

6.  **(Optional) Prepare `.gitignore`:**
    If you plan to use Git, ensure your `.gitignore` file prevents sensitive information from being committed. Create or edit `.gitignore` to include:
    ```gitignore
    .env
    user_threads_data.json
    __pycache__/
    *.pyc
    *.log # If you add file logging
    ```

## Running the Bot

Once setup is complete, you can run the bot from your terminal:

```bash
python your_bot_script_name.py
