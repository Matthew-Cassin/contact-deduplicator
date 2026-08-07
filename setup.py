from pathlib import Path

from setuptools import find_packages, setup

THIS_DIR = Path(__file__).parent
LONG_DESCRIPTION = (THIS_DIR / "README.md").read_text(encoding="utf-8")

setup(
    name="contact-deduplicator",
    version="0.1.0",
    description=(
        "A Python tool for detecting and merging duplicate contact "
        "records in CSV files."
    ),
    long_description=LONG_DESCRIPTION,
    long_description_content_type="text/markdown",
    author="Matt",
    license="MIT",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.8",
    install_requires=[
        "pandas>=3.0.5,<4.0.0",
        "click>=8.4.2,<9.0.0",
        "fuzzywuzzy>=0.18.0,<0.19.0",
        "python-Levenshtein>=0.27.3,<0.28.0",
        "email-phone-validator @ git+https://github.com/Matthew-Cassin/"
        "email-phone-validator.git@v0.1.0",
    ],
    entry_points={
        "console_scripts": [
            "contact-deduplicator=contact_deduplicator.cli:deduplicate",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3 :: Only",
        "Environment :: Console",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Office/Business",
    ],
    keywords="contact deduplication csv fuzzy-matching data-cleaning crm",
)
