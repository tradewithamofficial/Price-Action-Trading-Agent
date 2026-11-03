
import shutil
import subprocess
from http.client import responses
from pathlib import Path

# Project folder
PROJECT_DIR = Path(__file__).resolve().parent


# PROMPT_FILE = PROJECT_DIR / "ew_Intraday_independent.txt"
# RESPONSE_FILE = PROJECT_DIR / "responses/XAU_Nov02_NY.txt"

# PROMPT_FILE = PROJECT_DIR / "smc.txt"
# RESPONSE_FILE = PROJECT_DIR / "responses/BTC_Nov03_AS_1.txt"

PROMPT_FILE = PROJECT_DIR / "support_resistance.txt"
RESPONSE_FILE = PROJECT_DIR / "support_resistance_response.txt"

# PROMPT_FILE = PROJECT_DIR / "price_action.txt"
# RESPONSE_FILE = PROJECT_DIR / "price_action_response.txt"

# Change this to any supported Codex model ID.
DEFAULT_MODEL = "gpt-6-astra"


def main():
    # 1. Locate Codex CLI
    codex_path = shutil.which("codex")

    if not codex_path:
        print("ERROR: Codex CLI was not found.")
        print("Check that 'codex --version' works in PyCharm Terminal.")
        return

    # 2. Read prompt.txt
    if not PROMPT_FILE.exists():
        print("ERROR: prompt.txt was not found.")
        return

    prompt = PROMPT_FILE.read_text(encoding="utf-8").strip()

    if not prompt:
        print("ERROR: prompt.txt is empty.")
        return

    # 3. Select model
    print("Selected default model:", DEFAULT_MODEL)

    model = input(
        "Enter model ID (press Enter for default): "
    ).strip() or DEFAULT_MODEL

    # 4. Build Codex CLI command
    command = [
        codex_path,
        "exec",
        "--model", model,
        "--sandbox", "read-only",
        "--skip-git-repo-check",
        "--output-last-message", str(RESPONSE_FILE),
        "-"
    ]

    print("\nStarting Codex...")
    print("Model:", model)
    print("Prompt:", PROMPT_FILE.name)
    print("Please wait for the response...\n")

    # 5. Run Codex with prompt through stdin
    try:
        result = subprocess.run(
            command,
            input=prompt,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            cwd=PROJECT_DIR
        )
    except OSError as error:
        print("Could not start Codex:", error)
        return

    # 6. Display response or error
    if result.returncode != 0:
        print("Codex failed.")
        print(result.stderr or result.stdout)
        return

    if RESPONSE_FILE.exists():
        response = RESPONSE_FILE.read_text(
            encoding="utf-8"
        )

        print("========== ASTRA / CODEX RESPONSE ==========")
        print(response)
        print("============================================")

        print("\nResponse saved to:")
        print(RESPONSE_FILE)
    else:
        print("Codex finished, but no response file was found.")
        print(result.stdout)


if __name__ == "__main__":
    main()

