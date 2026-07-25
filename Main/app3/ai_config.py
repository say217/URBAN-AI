import os
from typing import AsyncGenerator
from langchain_groq import ChatGroq 
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

async def stream_chat_response(message: str, history: list, meta: dict) -> AsyncGenerator[str, None]:
    api_key = os.getenv("GROQ_API_KEY", "")
    
    llm = ChatGroq(
        model="llama-3.3-70b-versatile",
    )

    system_prompt = (
        "You are a concise data assistant embedded in a thermal-imaging dashboard. "
        "Answer questions about the currently loaded Landsat land-surface-temperature "
        "scene using only the metadata provided. Keep answers to 1-3 sentences.\n"
        f"Context: {meta}"
    )
    
    messages = [SystemMessage(content=system_prompt)]
    for msg in history:
        # history is a list of ChatMessage dicts or objects
        role = getattr(msg, "role", None) or msg.get("role", "")
        content = getattr(msg, "content", None) or msg.get("content", "")
        
        if role == 'user':
            messages.append(HumanMessage(content=content))
        else:
            messages.append(AIMessage(content=content))
            
    messages.append(HumanMessage(content=message))
    
    async for chunk in llm.astream(messages):
        if chunk.content:
            yield chunk.content
