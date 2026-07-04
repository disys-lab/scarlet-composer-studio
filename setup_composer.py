from setuptools import setup, find_packages

setup(
    name="scarletcomposer",
    use_scm_version={"fallback_version": "0.5.0"},
    setup_requires=["setuptools-scm"],
    author="Paritosh Ramanan",
    author_email="paritosh.ramanan@gmail.com",
    description="Scarlet Composer — operator UI and tooling for Scarlets deployments",
    long_description=open("README.md").read() if __import__("os").path.exists("README.md") else "",
    long_description_content_type="text/markdown",
    url="https://github.com/disys-lab/scarlet-composer-studio",
    license="Apache-2.0",
    packages=find_packages(include=["scarletcomposer", "scarletcomposer.*"]),
    package_data={
        "scarletcomposer": ["images/*"],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
    install_requires=[
        "scarlets",
        "click>=8.0.0",
        "requests>=2.28.0",
        "PyYAML>=6.0",
        "python-dotenv>=0.19.0",
        "streamlit>=1.37.0",
        "Pillow>=10.0.0",
        "docker>=7.0.0",
        "tornado>=6.0.0",
        "GitPython>=3.1.0",
    ],
    python_requires=">=3.9",
    entry_points={
        "console_scripts": [
            "scarlet-composer=scarletcomposer.composer.scarletDriver:scarletcomposer",
        ],
    },
)
