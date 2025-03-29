import discord
import asyncio
import openai
import os
import time
import json # Added for persistence
import logging # Added for better logging
from dotenv import load_dotenv # Import the library

# --- Load Configuration ---
load_dotenv() # Load variables from .env file into environment

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ASSISTANT_ID = os.getenv("ASSISTANT_ID")

# --- Persistence Setup (JSON Method) ---
THREAD_DATA_FILE = "user_threads_data.json"
user_threads = {} # Global dictionary for thread IDs (will be loaded)

def load_threads():
    """Loads the user_threads dictionary from the JSON file."""
    global user_threads
    try:
        with open(THREAD_DATA_FILE, 'r') as f:
            # Load data, converting string keys back to integer user IDs
            data_from_file = json.load(f)
            user_threads = {int(k): v for k, v in data_from_file.items()}
            logging.info(f"Loaded {len(user_threads)} user threads from {THREAD_DATA_FILE}")
    except FileNotFoundError:
        logging.warning(f"{THREAD_DATA_FILE} not found. Starting with empty threads.")
        user_threads = {}
    except json.JSONDecodeError:
        logging.error(f"Error decoding JSON from {THREAD_DATA_FILE}. Starting with empty threads.")
        user_threads = {} # Or potentially load a backup
    except Exception as e:
        logging.error(f"An unexpected error occurred loading threads: {e}")
        user_threads = {}

def save_threads():
    """Saves the current user_threads dictionary to the JSON file."""
    global user_threads
    try:
        with open(THREAD_DATA_FILE, 'w') as f:
            # Convert integer keys to strings for JSON compatibility
            data_to_save = {str(k): v for k, v in user_threads.items()}
            json.dump(data_to_save, f, indent=4) # Use indent for readability
        # logging.debug("User threads saved.") # Optional debug log
    except Exception as e:
        logging.error(f"Error saving threads to {THREAD_DATA_FILE}: {e}")

# --- Logging Setup ---
# Replace print statements with logging for better control
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
logger = logging.getLogger('discord_bot') # Optional: Use a specific logger name

# --- OpenAI Client Setup ---
# Check if the API key is still the placeholder (basic check)
if OPENAI_API_KEY.startswith("sk-proj-") is False or OPENAI_API_KEY == "": # Slightly better check
    logger.critical("OpenAI API key appears invalid or not configured. Please check the OPENAI_API_KEY variable.")
    exit()
try:
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
except Exception as e:
    logger.critical(f"Failed to initialize OpenAI client: {e}")
    exit()


# --- Discord Bot Setup ---
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.dm_messages = True # Ensure DMs are enabled

discord_client = discord.Client(intents=intents)

@discord_client.event
async def on_ready():
    logger.info(f'Logged in as {discord_client.user.name} ({discord_client.user.id})')
    logger.info('Assistant bot ready for DMs and Server Mentions.')
    logger.info('------')

@discord_client.event
async def on_message(message: discord.Message): # Added type hint
    # 1. Ignore messages from the bot itself
    if message.author == discord_client.user:
        return

    user_id = message.author.id # Get user_id early for logging/use

    # ----------------------------------------------------
    # 2. Handle Direct Messages (DMs)
    # ----------------------------------------------------
    if message.guild is None:
        logger.info(f"Received DM from {message.author} ({user_id}): {message.content[:50]}...") # Log start of message

        async with message.channel.typing():
            try:
                # --- Assistant Logic for DMs ---

                # 1. Get or Create Thread for the User
                thread_id = user_threads.get(user_id) # Check cache first
                if not thread_id:
                    logger.info(f"Creating new thread for user {user_id} (triggered by DM)")
                    try:
                        thread = client.beta.threads.create()
                        user_threads[user_id] = thread.id
                        thread_id = thread.id
                        save_threads() # <<< SAVE after adding to dict
                        logger.info(f"Thread created with ID: {thread_id} and saved.")
                    except Exception as api_error:
                        logger.error(f"Failed to create OpenAI thread for DM user {user_id}: {api_error}")
                        await message.channel.send("Sorry, I couldn't initiate our conversation context. Please try again later.")
                        return
                else:
                    logger.debug(f"Using existing thread {thread_id} for user {user_id}")


                # 2. Add User's Message to the Thread
                logger.debug(f"Adding message to thread {thread_id}")
                client.beta.threads.messages.create(
                    thread_id=thread_id,
                    role="user",
                    content=message.content # Use direct message content for DMs
                )

                # 3. Run the Assistant on the Thread
                logger.debug(f"Running assistant {ASSISTANT_ID} on thread {thread_id}")
                run = client.beta.threads.runs.create(
                    thread_id=thread_id,
                    assistant_id=ASSISTANT_ID,
                )

                # 4. Poll for Run Completion
                logger.debug(f"Polling run {run.id} status...")
                start_time = time.time()
                timeout_seconds = 120 # Increased timeout for potentially long runs

                while run.status in ['queued', 'in_progress', 'cancelling']:
                    await asyncio.sleep(1.5) # Slightly longer sleep
                    run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
                    # logger.debug(f"Run status: {run.status}") # Can be noisy
                    if time.time() - start_time > timeout_seconds:
                         logger.warning(f"Run {run.id} timed out waiting for completion.")
                         # Optionally try to cancel the run
                         try:
                             client.beta.threads.runs.cancel(thread_id=thread_id, run_id=run.id)
                             logger.info(f"Attempted to cancel timed-out run {run.id}")
                         except Exception as cancel_err:
                             logger.error(f"Failed to cancel timed-out run {run.id}: {cancel_err}")
                         await message.channel.send("Sorry, the request took too long to process. Please try again.")
                         return # Exit processing for this message

                # 5. Retrieve and Send Response TO THE DM CHANNEL
                if run.status == 'completed':
                    logger.debug(f"Run {run.id} completed. Fetching messages...")
                    messages_response = client.beta.threads.messages.list(
                        thread_id=thread_id,
                        order="asc" # Get messages in chronological order
                    )
                    assistant_responses = []
                    # Filter for messages from this specific run, most recent first
                    for msg in reversed(messages_response.data):
                        if msg.run_id == run.id and msg.role == "assistant":
                            for content_block in msg.content:
                                if content_block.type == 'text':
                                    assistant_responses.append(content_block.text.value)
                        # Optimization: Stop searching older messages once we hit a user message
                        # that wasn't part of *this* run (heuristic)
                        if msg.role == "user" and msg.run_id != run.id: # Check if run_id is None or different
                            break

                    # --- Check if we got a response ---
                    if assistant_responses:
                        # --- SUCCESS CASE ---
                        full_response = "\n".join(reversed(assistant_responses)) # Reverse back to correct order
                        logger.info(f"Sending Assistant Response to DM user {user_id}")

                        # --- Send response (Handle long messages for DM) ---
                        if len(full_response) <= 2000:
                           await message.channel.send(full_response)
                        else:
                            parts = [full_response[i:i+1990] for i in range(0, len(full_response), 1990)]
                            for part in parts:
                                await message.channel.send(part)
                                await asyncio.sleep(0.5) # Small delay between parts
                         # --- End of Success Case ---

                    else:
                        # --- FAILURE CASE: No response text found -> Reset Thread ---
                        logger.warning(f"No response text found from assistant for run {run.id}. Resetting thread for user {user_id} in DM.")

                        problematic_thread_id = user_threads.get(user_id) # Get the ID before removing mapping

                        # 1. Remove the thread mapping locally & save persistence
                        if user_id in user_threads:
                            del user_threads[user_id]
                            save_threads() # Save the updated dict (crucial for JSON method)
                            logger.info(f"Removed thread mapping for user {user_id} from persistence.")
                        else:
                            logger.warning(f"Attempted to reset thread for user {user_id}, but they weren't in the user_threads dict.")

                        # 2. (Optional but Recommended) Try to delete the thread on OpenAI's side
                        if problematic_thread_id:
                            logger.info(f"Attempting to delete problematic OpenAI thread: {problematic_thread_id}")
                            try:
                                # Make sure 'client' is your initialized OpenAI client
                                delete_status = client.beta.threads.delete(problematic_thread_id)
                                if delete_status.deleted:
                                    logger.info(f"Successfully deleted OpenAI thread {problematic_thread_id}.")
                                else:
                                     # This status might not always be accurate, log deletion attempt anyway
                                     logger.warning(f"OpenAI API attempt to delete thread {problematic_thread_id} completed (Status: {delete_status}). Deletion might still occur.")
                            except openai.NotFoundError:
                                logger.warning(f"OpenAI thread {problematic_thread_id} was already deleted or not found.")
                            except Exception as delete_error:
                                logger.error(f"Failed to delete OpenAI thread {problematic_thread_id}: {delete_error}")
                        else:
                             logger.warning(f"Could not attempt OpenAI thread deletion because thread ID was missing for user {user_id} during reset.")

                        # 3. Inform the user
                        # No mention needed in DMs
                        await message.channel.send("I seemed to have trouble retrieving the last response, so I've reset our conversation context. Please try sending your message again!")
                        # --- End of Reset Logic ---

                elif run.status == 'requires_action':
                    logger.warning(f"Run {run.id} requires action (not supported): {run.required_action}")
                    await message.channel.send("Sorry, I need to perform an action I can't do right now.")
                    # Note: You would handle function calls here if your assistant uses them.
                elif run.status == 'failed':
                     logger.error(f"Run {run.id} failed. Last Error: {run.last_error}")
                     # Provide a more specific error if possible
                     error_message = "Sorry, something went wrong while processing."
                     if run.last_error:
                         error_message += f" (Error code: {run.last_error.code})"
                     await message.channel.send(error_message)
                else: # 'cancelled', 'expired'
                    logger.error(f"Run {run.id} ended with unhandled status: {run.status}")
                    await message.channel.send(f"Sorry, the processing ended unexpectedly. (Status: {run.status})")

            except openai.RateLimitError:
                logger.warning(f"OpenAI Rate Limit hit for user {user_id} in DM.")
                await message.channel.send("I'm experiencing high demand right now. Please wait a moment and try again.")
            except openai.APIError as api_err:
                 logger.error(f"OpenAI API Error processing DM for {user_id}: {api_err}")
                 await message.channel.send("There was an issue communicating with the AI service. Please try again later.")
            except Exception as e:
                logger.exception(f"Unexpected error processing DM from {user_id}: {e}") # Log full traceback
                await message.channel.send("Sorry, I encountered an unexpected error trying to process your DM.")

    # ----------------------------------------------------
    # 3. Handle Server Messages (Guild Messages)
    # ----------------------------------------------------
    else:
        # Check if the bot was mentioned in the server message
        if discord_client.user.mentioned_in(message):

            if message.mention_everyone: # Optional: Ignore @everyone/@here
                logger.debug("Ignoring message with @everyone/@here mention.")
                return

            guild_id = message.guild.id
            channel_id = message.channel.id
            # user_id is already defined above

            logger.info(f"Received mention in Server '{message.guild.name}', Channel '{message.channel.name}' from {message.author}")

            # Clean the message content to remove the bot's mention
            # Handle both <@USER_ID> and <@!USER_ID> formats
            mention_patterns = [f'<@!{discord_client.user.id}>', f'<@{discord_client.user.id}>']
            actual_content = message.content
            for pattern in mention_patterns:
                actual_content = actual_content.replace(pattern, '')
            actual_content = actual_content.strip()


            # --- Check for 'dm' command --- (Optional - Placeholder if not used)
            # command_parts = actual_content.split(maxsplit=2)
            # if len(command_parts) >= 1 and command_parts[0].lower() == 'dm':
            #     logger.info("DM command detected (logic not included/placeholder).")
            #     await message.channel.send("DM command handling is placeholder.")
            #     return # Prevent falling through to assistant logic

            # --- Fallback to Assistant Logic if not a specific command ---
            if not actual_content: # Handle empty mention
                await message.channel.send(f"Hi {message.author.mention}, did you need something?")
                return

            # Process the request using the Assistant API
            async with message.channel.typing():
                try:
                    # 1. Get or Create Thread for the User (shared with DMs)
                    thread_id = user_threads.get(user_id) # Check cache first
                    if not thread_id:
                        logger.info(f"Creating new thread for user {user_id} (triggered by server mention)")
                        try:
                            thread = client.beta.threads.create()
                            user_threads[user_id] = thread.id
                            thread_id = thread.id
                            save_threads() # <<< SAVE after adding to dict
                            logger.info(f"Thread created with ID: {thread_id} and saved.")
                        except Exception as api_error:
                            logger.error(f"Failed to create OpenAI thread for user {user_id} (server mention): {api_error}")
                            await message.channel.send(f"{message.author.mention} Sorry, I couldn't initiate our conversation context. Please try again later.")
                            return
                    else:
                         logger.debug(f"Using existing thread {thread_id} for user {user_id}")


                    # 2. Add User's Message (the cleaned content) to the Thread
                    logger.debug(f"Adding message '{actual_content[:50]}...' to thread {thread_id}")
                    client.beta.threads.messages.create(
                        thread_id=thread_id,
                        role="user",
                        content=actual_content # Use the cleaned content for server mentions
                    )

                    # 3. Run the Assistant on the Thread
                    logger.debug(f"Running assistant {ASSISTANT_ID} on thread {thread_id}")
                    run = client.beta.threads.runs.create(
                        thread_id=thread_id,
                        assistant_id=ASSISTANT_ID,
                    )

                    # 4. Poll for Run Completion (same as DMs with timeout)
                    logger.debug(f"Polling run {run.id} status...")
                    start_time = time.time()
                    timeout_seconds = 120 # Increased timeout

                    while run.status in ['queued', 'in_progress', 'cancelling']:
                        await asyncio.sleep(1.5)
                        run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
                        # logger.debug(f"Run status: {run.status}")
                        if time.time() - start_time > timeout_seconds:
                            logger.warning(f"Run {run.id} timed out waiting for completion (server mention).")
                            try:
                                client.beta.threads.runs.cancel(thread_id=thread_id, run_id=run.id)
                                logger.info(f"Attempted to cancel timed-out run {run.id}")
                            except Exception as cancel_err:
                                logger.error(f"Failed to cancel timed-out run {run.id}: {cancel_err}")
                            await message.channel.send(f"{message.author.mention} Sorry, the request took too long to process. Please try again.")
                            return

                    # 5. Retrieve and Send Response TO THE SERVER CHANNEL
                    if run.status == 'completed':
                        logger.debug(f"Run {run.id} completed. Fetching messages...")
                        messages_response = client.beta.threads.messages.list(
                            thread_id=thread_id,
                            order="asc"
                        )
                        assistant_responses = []
                        for msg in reversed(messages_response.data):
                            if msg.run_id == run.id and msg.role == "assistant":
                                for content_block in msg.content:
                                    if content_block.type == 'text':
                                        assistant_responses.append(content_block.text.value)
                            if msg.role == "user" and msg.run_id != run.id:
                                break # Heuristic stop check

                        # --- Check if we got a response ---
                        if assistant_responses:
                            # --- SUCCESS CASE ---
                            full_response = "\n".join(reversed(assistant_responses))
                            logger.info(f"Sending Assistant Response to {message.author.name} in channel {message.channel.name}")

                            # --- Send response (Handle long messages for Server) ---
                            response_prefix = f"{message.author.mention} "
                            if len(response_prefix + full_response) <= 2000:
                                await message.channel.send(response_prefix + full_response)
                            else:
                                # Handle long messages for Server
                                await message.channel.send(response_prefix) # Send mention first
                                parts = [full_response[i:i+1990] for i in range(0, len(full_response), 1990)]
                                for part in parts:
                                    await message.channel.send(part)
                                    await asyncio.sleep(0.5) # Small delay between parts
                            # --- End of Success Case ---

                        else:
                            # --- FAILURE CASE: No response text found -> Reset Thread ---
                            logger.warning(f"No response text found from assistant for run {run.id}. Resetting thread for user {user_id} in server channel {channel_id}.")

                            problematic_thread_id = user_threads.get(user_id) # Get the ID before removing mapping

                            # 1. Remove the thread mapping locally & save persistence
                            if user_id in user_threads:
                                del user_threads[user_id]
                                save_threads() # Save the updated dict (crucial for JSON method)
                                logger.info(f"Removed thread mapping for user {user_id} from persistence.")
                            else:
                                logger.warning(f"Attempted to reset thread for user {user_id}, but they weren't in the user_threads dict.")

                            # 2. (Optional but Recommended) Try to delete the thread on OpenAI's side
                            if problematic_thread_id:
                                logger.info(f"Attempting to delete problematic OpenAI thread: {problematic_thread_id}")
                                try:
                                    # Make sure 'client' is your initialized OpenAI client
                                    delete_status = client.beta.threads.delete(problematic_thread_id)
                                    if delete_status.deleted:
                                        logger.info(f"Successfully deleted OpenAI thread {problematic_thread_id}.")
                                    else:
                                         logger.warning(f"OpenAI API attempt to delete thread {problematic_thread_id} completed (Status: {delete_status}). Deletion might still occur.")
                                except openai.NotFoundError:
                                    logger.warning(f"OpenAI thread {problematic_thread_id} was already deleted or not found.")
                                except Exception as delete_error:
                                    logger.error(f"Failed to delete OpenAI thread {problematic_thread_id}: {delete_error}")
                            else:
                                 logger.warning(f"Could not attempt OpenAI thread deletion because thread ID was missing for user {user_id} during reset.")

                            # 3. Inform the user
                            user_mention = f"{message.author.mention} " # Always mention in server
                            await message.channel.send(f"{user_mention}I seemed to have trouble retrieving the last response, so I've reset our conversation context. Please try sending your message again!".strip())
                            # --- End of Reset Logic ---


                    elif run.status == 'requires_action':
                        logger.warning(f"Run {run.id} requires action (not supported): {run.required_action}")
                        await message.channel.send(f"{message.author.mention} Sorry, I need to perform an action I can't do right now.")
                    elif run.status == 'failed':
                        logger.error(f"Run {run.id} failed. Last Error: {run.last_error}")
                        error_message = f"{message.author.mention} Sorry, something went wrong while processing."
                        if run.last_error:
                             error_message += f" (Error code: {run.last_error.code})"
                        await message.channel.send(error_message)
                    else: # includes 'cancelled', 'expired'
                        logger.error(f"Run {run.id} ended with unhandled status: {run.status}")
                        await message.channel.send(f"{message.author.mention} Sorry, the processing ended unexpectedly. (Status: {run.status})")

                except openai.RateLimitError:
                    logger.warning(f"OpenAI Rate Limit hit for user {user_id} in server {guild_id}.")
                    await message.channel.send(f"{message.author.mention} I'm experiencing high demand right now. Please wait a moment and try again.")
                except openai.APIError as api_err:
                     logger.error(f"OpenAI API Error processing server mention for {user_id} in {guild_id}: {api_err}")
                     await message.channel.send(f"{message.author.mention} There was an issue communicating with the AI service. Please try again later.")
                except Exception as e:
                    logger.exception(f"Unexpected error processing server mention from {user_id} in {guild_id}: {e}") # Log full traceback
                    await message.channel.send(f"{message.author.mention} Sorry, I encountered an unexpected error trying to process that.")

        # else: (Implicit) Message in server, bot not mentioned. Ignore silently.

# --- Run the Bot ---
if __name__ == "__main__": # Use main guard
    # Basic validation before starting
    if DISCORD_BOT_TOKEN.startswith("M") is False or DISCORD_BOT_TOKEN == "" or len(DISCORD_BOT_TOKEN) < 50: # Basic token format check
        logger.critical("Discord Bot Token appears invalid or not configured. Please check the DISCORD_BOT_TOKEN variable.")
        exit()
    if not ASSISTANT_ID.startswith("asst_"):
         logger.critical("OpenAI Assistant ID appears invalid (must start with 'asst_'). Please check the ASSISTANT_ID variable.")
         exit()

    try:
        # Validate Assistant ID exists before running
        try:
            client.beta.assistants.retrieve(ASSISTANT_ID)
            logger.info(f"Successfully retrieved Assistant {ASSISTANT_ID}")
        except openai.AuthenticationError:
             logger.critical(f"ERROR: OpenAI Authentication Error. Is the API key ({OPENAI_API_KEY[:6]}...) correct and valid?")
             exit()
        except openai.NotFoundError:
            logger.critical(f"ERROR: Could not find Assistant {ASSISTANT_ID}. Is the ID correct?")
            exit()
        except Exception as e:
            logger.critical(f"ERROR: Could not retrieve Assistant {ASSISTANT_ID}. Unexpected error: {e}")
            exit() # Exit if assistant validation fails

        # Load existing thread data before starting the client
        load_threads()

        logger.info("Starting Discord client...")
        discord_client.run(DISCORD_BOT_TOKEN)

    except discord.errors.LoginFailure:
        logger.critical("ERROR: Invalid Discord Token. Please check your DISCORD_BOT_TOKEN.")
    except discord.errors.PrivilegedIntentsRequired:
         logger.critical("ERROR: Required Discord Intents (Messages, Message Content, DMs) are not enabled for the bot in the Discord Developer Portal.")
    except Exception as e:
        logger.exception(f"A critical error occurred preventing the bot from running: {e}") # Log full traceback for critical errors