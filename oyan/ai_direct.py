"""The second way to reach the AI: straight to the Anthropic API with a key.

This is only used when an API key has been saved (see settings.py). People
who have Claude Code installed do not need it; see ai.py for that way.

We use `anthropic`, the official Python package. The screenshot is sent
inside the request itself, already turned into text with "base64" by ai.py.
No tools are given to the model here either: it can only answer.
"""

import anthropic

API_MODEL = "claude-opus-5-5"
API_EFFORT = "low"        # how hard the model thinks: low is quickest
MAX_REPLY_TOKENS = 8000   # upper limit on the reply (includes its thinking)


class AIError(Exception):
    """Something went wrong; the message is safe to show to the owner."""


def ask_with_key(api_key, system_prompt, image_data, text, timeout_seconds):
    """Send the picture (as base64 text) and the question. Returns the reply."""
    client = anthropic.Anthropic(api_key=api_key, timeout=timeout_seconds)

    try:
        response = client.beta.messages.create(
            model=API_MODEL,
            max_tokens=MAX_REPLY_TOKENS,
            output_config={"effort": API_EFFORT},
            system=system_prompt,
            # If the model declines a request, let the service retry it on
            # another model instead of just stopping.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data},
                    },
                    {"type": "text", "text": text},
                ],
            }],
        )
    except anthropic.AuthenticationError:
        raise AIError("The saved API key was not accepted. Set it again with --set-key.")
    except anthropic.PermissionDeniedError:
        raise AIError("The saved API key is not allowed to do this.")
    except anthropic.RateLimitError:
        raise AIError("Too many requests for this API key right now. Try again in a minute.")
    except anthropic.APIStatusError as error:
        raise AIError(f"The AI service returned an error ({error.status_code}).")
    except anthropic.APIConnectionError:
        raise AIError("Could not reach the AI service. Check the internet connection.")

    if response.stop_reason == "refusal":
        raise AIError("The AI declined to answer this one.")

    # The reply is a list of blocks; the answer is in the "text" ones.
    return "".join(block.text for block in response.content if block.type == "text")
