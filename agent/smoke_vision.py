"""Go/no-go: can the ChatGPT-authenticated Codex backend read a P&ID image?"""

import base64
import sys
from pathlib import Path

from langchain_core.messages import HumanMessage
from langchain_openai.chat_models.codex import _ChatOpenAICodex

image = Path(sys.argv[1] if len(sys.argv) > 1 else "samples/open100-0.png")
b64 = base64.b64encode(image.read_bytes()).decode()
mime = "image/png" if image.suffix == ".png" else "image/jpeg"

import os

model = _ChatOpenAICodex(model=os.environ.get("MODEL", "gpt-5.5"), instructions="You read engineering drawings.")
reply = model.invoke(
    [
        HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": "List the instrument tags you can read in this P&ID (e.g. TCV 1401), then the drawing title from the title block.",
                },
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ]
        )
    ]
)
print(reply.text)
