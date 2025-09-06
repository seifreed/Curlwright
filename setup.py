"""
Setup script for CurlWright
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read the contents of README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text(encoding="utf-8")

# Read requirements from file if it exists
try:
    requirements = (this_directory / "requirements.txt").read_text(encoding="utf-8").splitlines()
    requirements = [line.strip() for line in requirements if line.strip() and not line.startswith("#")]
except:
    requirements = ["playwright>=1.40.0", "asyncio>=3.4.3"]

setup(
    name="curlwright",
    version="1.0.0",
    author="Marc Rivero",
    author_email="mriverolopez@gmail.com",
    description="Cloudflare bypass tool using Playwright for curl requests",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/seifreed/Curlwright",
    project_urls={
        "Bug Tracker": "https://github.com/seifreed/Curlwright/issues",
        "Documentation": "https://github.com/seifreed/Curlwright#readme",
        "Source Code": "https://github.com/seifreed/Curlwright",
    },
    packages=find_packages(include=["curlwright", "curlwright.*", "src", "src.*"]),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Software Development :: Testing",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    python_requires=">=3.9",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "curlwright=curlwright.cli:main",
        ],
    },
    keywords=[
        "cloudflare",
        "bypass",
        "playwright",
        "curl",
        "web scraping",
        "automation",
        "browser automation",
        "turnstile",
    ],
    license="MIT",
    include_package_data=True,
    zip_safe=False,
)