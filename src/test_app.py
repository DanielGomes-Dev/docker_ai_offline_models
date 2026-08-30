"""Tests for the app factory. main.py is 2 lines; importing src.app has no side effect."""

from fastapi import FastAPI

from src.app import create_app


def test_create_app_metadata():
    app = create_app()
    assert isinstance(app, FastAPI)
    assert app.title == "AI Inference API"
    assert app.version == "1.0.0"
    assert len(app.description) > 0


def test_mounts_the_media_routes():
    paths = set(create_app().openapi()["paths"])
    assert "/tts" in paths or "/transcribe" in paths
