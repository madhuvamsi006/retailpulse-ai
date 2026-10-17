"""
Shared Gemini client using Vertex AI (ADC-compatible, works with service accounts).
All agents import from here instead of google.generativeai directly.
"""
import os
import vertexai
from vertexai.generative_models import GenerativeModel, Tool, FunctionDeclaration, Content, Part
import config

_initialized = False


def init():
    global _initialized
    if not _initialized:
        vertexai.init(project=config.GCP_PROJECT_ID, location=config.GCP_REGION)
        _initialized = True


def get_model(system_instruction: str | None = None) -> GenerativeModel:
    init()
    kwargs = {"model_name": config.GEMINI_MODEL}
    if system_instruction:
        kwargs["system_instruction"] = system_instruction
    return GenerativeModel(**kwargs)


def generate(model: GenerativeModel, prompt: str) -> str:
    response = model.generate_content(prompt)
    return response.text


def generate_with_tools(model: GenerativeModel, messages: list, tools: list | None = None) -> object:
    response = model.generate_content(messages, tools=tools or [])
    return response
