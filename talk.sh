#!/bin/bash
set -euo pipefail

# === Configuration ===
WHISPER_MODEL="${WHISPER_MODEL:-/tmp/ggml-small.en.bin}"
WHISPER_MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin"
RECORD_SECONDS="${RECORD_SECONDS:-8}"
SAMPLE_RATE=16000
AUDIO_DEVICE="${AUDIO_DEVICE:-:1}"  # macOS audio device index (check with: ffmpeg -f avfoundation -list_devices true -i "")
VOLUME_THRESHOLD="${VOLUME_THRESHOLD:-0.02}"  # amplitude threshold to filter silence/hallucinations
TMP_DIR=$(mktemp -d)
CONVERSATION_FILE="$TMP_DIR/conversation.txt"
VOICE="${VOICE:-Daniel}"  # macOS TTS voice (try: Samantha, Karen, Moira, Daniel)

# Colors
BOLD='\033[1m'
DIM='\033[2m'
CYAN='\033[36m'
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
RESET='\033[0m'

# === Cleanup ===
cleanup() {
    echo -e "\n${DIM}Cleaning up...${RESET}"
    rm -rf "$TMP_DIR"
    exit 0
}
trap cleanup INT TERM

# === Dependency check ===
check_deps() {
    local missing=()
    command -v ffmpeg >/dev/null || missing+=(ffmpeg)
    command -v whisper-cpp >/dev/null || missing+=(whisper-cpp)
    command -v claude >/dev/null || missing+=(claude)
    command -v say >/dev/null || missing+=(say)
    command -v afplay >/dev/null || missing+=(afplay)

    if [[ ${#missing[@]} -gt 0 ]]; then
        echo -e "${RED}Missing dependencies: ${missing[*]}${RESET}"
        exit 1
    fi

    if [[ ! -f "$WHISPER_MODEL" ]]; then
        echo -e "${YELLOW}Downloading whisper model (small.en, ~465MB)...${RESET}"
        curl -L "$WHISPER_MODEL_URL" -o "$WHISPER_MODEL"
    fi
}

# === Record audio ===
record_audio() {
    local output="$1"
    local duration="$2"

    ffmpeg -f avfoundation -i "$AUDIO_DEVICE" \
        -t "$duration" -ar "$SAMPLE_RATE" -ac 1 \
        "$output" -y -loglevel quiet
}

# === Check if audio has actual speech (not silence) ===
has_speech() {
    local audio_file="$1"
    local amp
    amp=$(sox "$audio_file" -n stat 2>&1 | grep "Maximum amplitude" | awk '{print $3}')
    if command -v bc >/dev/null; then
        [[ $(echo "$amp > $VOLUME_THRESHOLD" | bc -l) -eq 1 ]]
    else
        # Fallback: just check it's not zero
        [[ "$amp" != "0.000000" ]]
    fi
}

# === Transcribe audio ===
transcribe() {
    local audio_file="$1"
    whisper-cpp -m "$WHISPER_MODEL" -f "$audio_file" \
        --no-timestamps -t 4 2>/dev/null | sed 's/^[[:space:]]*//'
}

# === Send to Claude ===
ask_claude() {
    local user_text="$1"

    # Build the prompt with conversation context
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

    # Append to conversation history
    echo "User: $user_text" >> "$CONVERSATION_FILE"
    echo "Assistant: $response" >> "$CONVERSATION_FILE"
}

# === Speak response ===
speak() {
    local text="$1"
    say -v "$VOICE" "$text"
}

# === Play a short beep to signal recording start/stop ===
beep() {
    afplay /System/Library/Sounds/Tink.aiff 2>/dev/null &
}

# === Main loop ===
main() {
    check_deps

    echo -e "${BOLD}${CYAN}"
    echo "  ╔══════════════════════════════════════╗"
    echo "  ║       Claude Voice Chat              ║"
    echo "  ║  Speak naturally, Ctrl+C to quit     ║"
    echo "  ╚══════════════════════════════════════╝"
    echo -e "${RESET}"
    echo -e "${DIM}Recording duration: ${RECORD_SECONDS}s | Voice: $VOICE${RESET}"
    echo -e "${DIM}Tip: RECORD_SECONDS=10 ./talk.sh for longer recordings${RESET}"
    echo ""

    local turn=0
    while true; do
        ((turn++))

        # Record
        local audio_file="$TMP_DIR/input_${turn}.wav"
        echo -e "${GREEN}🎙  Listening... (${RECORD_SECONDS}s)${RESET}"
        beep
        record_audio "$audio_file" "$RECORD_SECONDS"
        beep

        # Check for actual speech (prevents whisper hallucinations on silence)
        if ! has_speech "$audio_file"; then
            echo -e "${DIM}   (silence, skipping)${RESET}"
            echo ""
            rm -f "$audio_file"
            continue
        fi

        # Transcribe
        echo -e "${YELLOW}📝 Transcribing...${RESET}"
        local transcript
        transcript=$(transcribe "$audio_file")

        if [[ -z "$transcript" || "$transcript" =~ ^[[:space:]]*$ ]]; then
            echo -e "${DIM}   (no speech detected, skipping)${RESET}"
            echo ""
            rm -f "$audio_file"
            continue
        fi

        echo -e "${DIM}   You said: \"$transcript\"${RESET}"

        # Ask Claude
        echo -e "${CYAN}🤖 Thinking...${RESET}"
        local response
        response=$(ask_claude "$transcript")
        echo -e "${BOLD}   Claude: $response${RESET}"

        # Speak
        speak "$response"
        echo ""

        # Cleanup old audio to save disk
        rm -f "$audio_file"
    done
}

main "$@"
