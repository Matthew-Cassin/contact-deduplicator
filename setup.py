from setuptools import setup, find_packages

setup(
    name="contact-deduplicator",
    version="0.1.0",
    description="A Python tool for detecting and merging duplicate contact records.",
    author="Matt",
    license="MIT",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.8",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
    ],
)
