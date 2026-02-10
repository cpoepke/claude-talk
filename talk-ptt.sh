#!/bin/bash
set -euo pipefail

# === Push-to-Talk Voice Chat with Claude ===
# Press Enter to start/stop recording (spacebar detection requires stty tricks)

WHISPER_MODEL="${WHISPER_MODEL:-/tmp/ggml-small.en.bin}"
WHISPER_MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin"
SAMPLE_RATE=16000
AUDIO_DEVICE="${AUDIO_DEVICE:-:1}"  # macOS audio device index
VOLUME_THRESHOLD="${VOLUME_THRESHOLD:-0.02}"
TMP_DIR=$(mktemp -d)
CONVERSATION_FILE="$TMP_DIR/conversation.txt"
VOICE="${VOICE:-Daniel}"

BOLD='\033[1m'
DIM='\033[2m'
CYAN='\033[36m'
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
RESET='\033[0m'

cleanup() {
    # Restore terminal settings
    stty "$SAVED_TTY" 2>/dev/null || true
    echo -e "\n${DIM}Goodbye!${RESET}"
    rm -rf "$TMP_DIR"
    exit 0
}
trap cleanup INT TERM EXIT

check_deps() {
    local missing=()
    command -v ffmpeg >/dev/null || missing+=(ffmpeg)
    command -v whisper-cpp >/dev/null || missing+=(whisper-cpp)
    command -v claude >/dev/null || missing+=(claude)
    command -v say >/dev/null || missing+=(say)

    if [[ ${#missing[@]} -gt 0 ]]; then
        echo -e "${RED}Missing: ${missing[*]}${RESET}"
        exit 1
    fi

    if [[ ! -f "$WHISPER_MODEL" ]]; then
        echo -e "${YELLOW}Downloading whisper model (small.en, ~465MB)...${RESET}"
        curl -L "$WHISPER_MODEL_URL" -o "$WHISPER_MODEL"
    fi
}

record_until_enter() {
    local output="$1"

    # Start recording in background
    ffmpeg -f avfoundation -i "$AUDIO_DEVICE" \
        -ar "$SAMPLE_RATE" -ac 1 \
        "$output" -y -loglevel quiet &
    local ffmpeg_pid=$!

    # Wait for Enter key
    read -r -s

    # Stop recording
    kill "$ffmpeg_pid" 2>/dev/null
    wait "$ffmpeg_pid" 2>/dev/null || true
}

transcribe() {
    local audio_file="$1"
    whisper-cpp -m "$WHISPER_MODEL" -f "$audio_file" \
        --no-timestamps -t 4 2>/dev/null | sed 's/^[[:space:]]*//'
}

ask_claude() {
    local user_text="$1"

    local prompt
    if [[ -f "$CONVERSATION_FILE" && -s "$CONVERSATION_FILE" ]]; then
        prompt="$(cat "$CONVERSATION_FILE")

User: $user_text

Reply concisely in 1-3 sentences. Be conversational."
    else
        prompt="You are having a spoken conversation. The user's speech has been transcribed and may contain minor errors. Reply concisely in 1-3 sentences. Be conversational and natural.

User: $user_text"
    fi

    local response
    response=$(claude -p "$prompt" 2>/dev/null)
    echo "$response"

    echo "User: $user_text" >> "$CONVERSATION_FILE"
    echo "Assistant: $response" >> "$CONVERSATION_FILE"
}

speak() {
    say -v "$VOICE" "$1"
}

main() {
    check_deps
    SAVED_TTY=$(stty -g)

    echo -e "${BOLD}${CYAN}"
    echo "  ╔══════════════════════════════════════╗"
    echo "  ║    Claude Voice Chat (Push-to-Talk)  ║"
    echo "  ║  Press Enter to start/stop recording ║"
    echo "  ║  Ctrl+C to quit                      ║"
    echo "  ╚══════════════════════════════════════╝"
    echo -e "${RESET}"
    echo -e "${DIM}Voice: $VOICE | Model: base.en${RESET}"
    echo ""

    local turn=0
    while true; do
        ((turn++))
        local audio_file="$TMP_DIR/input_${turn}.wav"

        # Wait for user to press Enter to start
        echo -e "${GREEN}Press Enter to start recording...${RESET}"
        read -r -s

        # Record until Enter pressed again
        echo -e "${RED}● Recording... press Enter to stop${RESET}"
        afplay /System/Library/Sounds/Tink.aiff 2>/dev/null &
        record_until_enter "$audio_file"
        afplay /System/Library/Sounds/Tink.aiff 2>/dev/null &

        # Check if file has content
        if [[ ! -f "$audio_file" ]] || [[ $(wc -c < "$audio_file") -lt 1000 ]]; then
            echo -e "${DIM}   (too short, skipping)${RESET}"
            echo ""
            continue
        fi

        # Transcribe
        echo -e "${YELLOW}📝 Transcribing...${RESET}"
        local transcript
        transcript=$(transcribe "$audio_file")

        if [[ -z "$transcript" || "$transcript" =~ ^[[:space:]]*$ ]]; then
            echo -e "${DIM}   (no speech detected)${RESET}"
            echo ""
            rm -f "$audio_file"
            continue
        fi

        echo -e "${DIM}   You: \"$transcript\"${RESET}"

        # Ask Claude
        echo -e "${CYAN}🤖 Thinking...${RESET}"
        local response
        response=$(ask_claude "$transcript")
        echo -e "${BOLD}   Claude: $response${RESET}"

        # Speak
        speak "$response"
        echo ""

        rm -f "$audio_file"
    done
}

main "$@"
