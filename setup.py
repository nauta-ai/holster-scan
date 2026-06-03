from setuptools import find_packages, setup


setup(
    name="holster-scan",
    version="0.0.1",
    description="Local-first scanner for hallucinated and typosquatted package imports.",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="Nauta AI",
    url="https://nautaai.com",
    packages=find_packages(),
    python_requires=">=3.9",
    entry_points={"console_scripts": ["holster-scan=holster_scan.cli:main"]},
)
