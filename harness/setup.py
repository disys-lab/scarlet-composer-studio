from setuptools import setup, find_packages

setup(
    name="scarlet-agentic-harness",
    version="0.1.0",
    author="Paritosh Ramanan",
    author_email="paritosh.ramanan@gmail.com",
    description="Generalized decentralized agentic Skill harness built on scarlet-composer-studio primitives",
    long_description=open("README.md").read() if __import__("os").path.exists("README.md") else "",
    long_description_content_type="text/markdown",
    url="https://github.com/disys-lab/scarlet-agentic-harness",
    license="Apache-2.0",
    packages=find_packages(include=["scarlet_agentic_harness", "scarlet_agentic_harness.*"]),
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
    install_requires=[
        "scarlets @ git+https://github.com/disys-lab/scarlet-composer-studio.git",
        "openai>=1.0.0",
        "mcp>=2.0.0",
    ],
    python_requires=">=3.10",
)
