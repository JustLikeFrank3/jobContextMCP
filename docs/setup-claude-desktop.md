# Setting Up jobContextMCP with Claude Desktop

## Prerequisite
Make sure Claude Desktop is installed. If not: https://claude.ai/download

---

## Step 1 — Install Python 3
Open Terminal and run:
```
python3 --version
```
If it says "command not found", download Python from https://python.org/downloads and install it.

---

## Step 2 — Clone the repo
In Terminal:
```
git clone https://github.com/JustLikeFrank3/jobContextMCP
cd jobContextMCP
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

---

## Step 3 — Create the config file
Still in that folder:
```
cp config.example.json config.json
```
Open `config.json` in any text editor. Fill in your name, email, phone, LinkedIn. The `openai_api_key` field can be left blank for now — it's only needed for RAG search features, not tone samples or outreach.

---

## Step 4 — Wire it to Claude Desktop
Open this file in a text editor (create it if it doesn't exist):
- **Mac:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

Paste this, replacing the paths with wherever you cloned the repo:
```json
{
  "mcpServers": {
    "jobContextMCP": {
      "command": "/absolute/path/to/jobContextMCP/.venv/bin/python3",
      "args": ["/absolute/path/to/jobContextMCP/server.py"],
      "cwd": "/absolute/path/to/jobContextMCP"
    }
  }
}
```
Example on Mac: `/Users/yourname/jobContextMCP/.venv/bin/python3`

---

## Step 5 — Bootstrap your workspace
Restart Claude Desktop. Then in a Claude chat, say:
> "Run setup_workspace and walk me through it."

The tool will ask for your info and create all your data files from scratch.

---

## Step 6 — Add tone samples
Ask Claude to `log_tone_sample` from any message you write. After a few samples, `get_tone_profile` will reflect your voice and Claude can draft outreach in your register.

---

## Note on work computers
IT restrictions may block running local scripts or modifying app config files. If you hit permission walls, Docker is the cleaner option — requires Docker Desktop installed. Check with IT first if unsure.
