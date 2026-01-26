"""LLM Assistant Page Object for Streamlit dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.pages.base_page import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


class LLMAssistantPage(BasePage):
    """Page Object for the LLM Assistant page."""

    PAGE_PATH = "LLM_Assistant"

    def __init__(self, page: "Page", base_url: str) -> None:
        """Initialize the LLM assistant page.

        Args:
            page: Playwright page object
            base_url: Base URL of the Streamlit application
        """
        super().__init__(page, base_url)
        self.streaming_timeout = 30000  # Longer timeout for LLM responses

    def navigate(self) -> None:
        """Navigate to the LLM Assistant page."""
        self.click_sidebar_link("LLM Assistant")

    def get_chat_input(self) -> "Locator":
        """Get the chat input field.

        Returns:
            Locator for the chat input
        """
        return self.page.locator("[data-testid='stChatInput'] input")

    def send_message(self, message: str) -> None:
        """Send a message in the chat.

        Args:
            message: Message text to send
        """
        chat_input = self.get_chat_input()
        chat_input.fill(message)
        chat_input.press("Enter")

    def wait_for_response(self, timeout: int | None = None) -> None:
        """Wait for the LLM response to complete streaming.

        Args:
            timeout: Maximum time to wait in milliseconds
        """
        timeout = timeout or self.streaming_timeout

        # Wait for streaming to complete (cursor character disappears)
        self.page.wait_for_function(
            """() => {
                const messages = document.querySelectorAll('[data-testid="stChatMessage"]');
                if (messages.length < 2) return false;
                const lastMessage = messages[messages.length - 1];
                // Check that streaming cursor is gone
                return !lastMessage.textContent.includes('▌');
            }""",
            timeout=timeout,
        )

    def get_message_count(self) -> int:
        """Get the number of chat messages displayed.

        Returns:
            Number of chat messages
        """
        messages = self.page.locator("[data-testid='stChatMessage']")
        return messages.count()

    def get_last_response(self) -> str | None:
        """Get the text of the last assistant response.

        Returns:
            Response text or None if no response
        """
        messages = self.page.locator("[data-testid='stChatMessage']")
        if messages.count() < 2:
            return None
        return messages.last.text_content()

    def get_all_messages(self) -> list[str]:
        """Get all chat messages.

        Returns:
            List of message texts
        """
        messages = self.page.locator("[data-testid='stChatMessage']")
        return [msg.text_content() or "" for msg in messages.all()]

    def is_chat_input_visible(self) -> bool:
        """Check if the chat input is visible.

        Returns:
            True if chat input is visible
        """
        return self.is_element_visible("[data-testid='stChatInput']")

    def click_quick_question(self, question_text: str) -> None:
        """Click a quick question button in the sidebar.

        Args:
            question_text: Text of the quick question to click
        """
        sidebar = self.page.locator("[data-testid='stSidebar']")
        button = sidebar.locator(f"button:has-text('{question_text}')")
        if button.count() > 0:
            button.first.click()

    def clear_chat_history(self) -> None:
        """Clear the chat history."""
        clear_button = self.page.locator("button:has-text('Clear')")
        if clear_button.count() > 0:
            clear_button.click()

    def is_streaming(self) -> bool:
        """Check if the assistant is currently streaming a response.

        Returns:
            True if streaming is in progress
        """
        messages = self.page.locator("[data-testid='stChatMessage']")
        if messages.count() == 0:
            return False
        last_message = messages.last
        content = last_message.text_content() or ""
        # Streaming cursor character
        return "▌" in content

    def wait_for_chat_ready(self, timeout: int = 10000) -> None:
        """Wait for the chat interface to be ready.

        Args:
            timeout: Maximum time to wait in milliseconds
        """
        self.page.wait_for_selector("[data-testid='stChatInput']", timeout=timeout)
        self.wait_for_streamlit_ready()

    def get_quick_questions(self) -> list[str]:
        """Get available quick questions from the sidebar.

        Returns:
            List of quick question texts
        """
        sidebar = self.page.locator("[data-testid='stSidebar']")
        buttons = sidebar.locator("button")
        return [btn.text_content() or "" for btn in buttons.all() if "?" in (btn.text_content() or "")]

    def has_connection_error(self) -> bool:
        """Check if there's a connection error displayed.

        Returns:
            True if connection error is shown
        """
        return (
            self.page.locator(":has-text('Connection error')").count() > 0
            or self.page.locator(":has-text('Failed to connect')").count() > 0
        )

    def get_model_info(self) -> str | None:
        """Get the current LLM model information if displayed.

        Returns:
            Model info text or None
        """
        sidebar = self.page.locator("[data-testid='stSidebar']")
        model_info = sidebar.locator(":has-text('Model:')")
        if model_info.count() == 0:
            return None
        return model_info.first.text_content()
