"""LLM Assistant - Chat interface with infrastructure context."""

from __future__ import annotations

import json
import streamlit as st
from websockets.sync.client import connect as ws_connect
from websockets.exceptions import WebSocketException

import sys
sys.path.insert(0, str(__file__).rsplit("pages", 1)[0])
from api_client import get_api_client, BACKEND_URL
from shared import require_auth


st.set_page_config(
    page_title="LLM Assistant - Portainer Dashboard",
    page_icon="💬",
    layout="wide",
)


def render_sidebar():
    """Render sidebar with session info and LLM controls."""
    client = get_api_client()
    with st.sidebar:
        st.markdown(f"**Logged in as:** {st.session_state.get('username', 'User')}")

        # Session timeout display
        session_info = client.get_session_status()
        if session_info:
            minutes_remaining = session_info.get("minutes_remaining", 0)
            seconds_remaining = session_info.get("seconds_remaining", 0)
            if minutes_remaining > 5:
                st.caption(f"Session expires in {minutes_remaining} min")
            elif minutes_remaining > 0:
                secs = seconds_remaining % 60
                st.warning(f"Session expires in {minutes_remaining}:{secs:02d}")
            else:
                st.error(f"Session expires in {seconds_remaining}s")

        if st.button("Logout", use_container_width=True):
            client.logout()
            st.rerun()
        st.markdown("---")

        # Chat controls
        st.markdown("### Chat Settings")
        if st.button("🗑️ Clear Chat History", use_container_width=True):
            st.session_state["chat_messages"] = []
            st.rerun()

        st.markdown("---")
        st.markdown("### Quick Questions")
        quick_questions = [
            "How many containers are running?",
            "Show me unhealthy containers",
            "Which endpoints are offline?",
            "What's the status of my infrastructure?",
            "List all running containers",
        ]
        for q in quick_questions:
            if st.button(q, use_container_width=True, key=f"quick_{q[:20]}"):
                st.session_state["pending_question"] = q
                st.rerun()


def get_websocket_url() -> str:
    """Get the WebSocket URL for LLM chat."""
    # Convert HTTP URL to WebSocket URL
    ws_url = BACKEND_URL.replace("http://", "ws://").replace("https://", "wss://")
    return f"{ws_url}/ws/llm/chat"


def stream_llm_response(messages: list[dict]) -> str:
    """Stream response from LLM via WebSocket."""
    ws_url = get_websocket_url()
    full_response = ""

    try:
        with ws_connect(ws_url, close_timeout=5) as websocket:
            # Send the messages
            websocket.send(json.dumps({"messages": messages}))

            # Receive streaming response
            while True:
                try:
                    message = websocket.recv(timeout=60)
                    data = json.loads(message)

                    if data["type"] == "chunk":
                        full_response += data["content"]
                        yield data["content"]
                    elif data["type"] == "done":
                        break
                    elif data["type"] == "error":
                        yield f"\n\n**Error:** {data['content']}"
                        break
                except TimeoutError:
                    yield "\n\n**Error:** Response timed out"
                    break

    except WebSocketException as e:
        yield f"\n\n**Connection Error:** Could not connect to LLM service. {str(e)}"
    except Exception as e:
        yield f"\n\n**Error:** {str(e)}"

    return full_response


def process_llm_query(prompt: str) -> None:
    """Process a user query and get LLM response."""
    # Add user message
    st.session_state["chat_messages"].append({"role": "user", "content": prompt})

    # Display user message
    with st.chat_message("user"):
        st.markdown(prompt)

    # Generate and display assistant response
    with st.chat_message("assistant"):
        message_placeholder = st.empty()

        # Prepare messages for API (only role and content)
        api_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in st.session_state["chat_messages"]
        ]

        # Stream the response
        full_response = ""
        for chunk in stream_llm_response(api_messages):
            full_response += chunk
            message_placeholder.markdown(full_response + "▌")

        message_placeholder.markdown(full_response)

    # Add assistant response to history
    st.session_state["chat_messages"].append({
        "role": "assistant",
        "content": full_response
    })


def main():
    """LLM Assistant page."""
    require_auth()
    render_sidebar()

    st.title("💬 LLM Assistant")
    st.markdown("Ask questions about your Portainer infrastructure")

    # Initialize chat history
    if "chat_messages" not in st.session_state:
        st.session_state["chat_messages"] = []

    # Handle pending question from quick questions
    pending_question = st.session_state.pop("pending_question", None)

    # Display existing chat messages
    for message in st.session_state["chat_messages"]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Process pending question from sidebar
    if pending_question:
        process_llm_query(pending_question)

    # Chat input
    if prompt := st.chat_input("Ask about your infrastructure..."):
        process_llm_query(prompt)

    # Show example prompts if no messages
    if not st.session_state["chat_messages"]:
        st.markdown("---")
        st.markdown("### Example Questions")

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("""
            **Infrastructure Status:**
            - "How many containers are running?"
            - "Show me the status of all endpoints"
            - "Are there any unhealthy containers?"
            """)

        with col2:
            st.markdown("""
            **Troubleshooting:**
            - "Which containers have restarted recently?"
            - "What endpoints are offline?"
            - "List containers using the most resources"
            """)


if __name__ == "__main__":
    main()
