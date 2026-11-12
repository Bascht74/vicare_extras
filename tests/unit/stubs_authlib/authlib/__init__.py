"""Minimal stand-in for authlib, used only by test_real_pyvicare.py when the
real authlib is not installed. PyViCare's OAuth manager base class imports two
exception classes and one session class from authlib; nothing else is needed.
"""
