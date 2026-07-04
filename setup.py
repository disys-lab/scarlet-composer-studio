from setuptools import setup, find_packages

setup(
    name="scarlets",
    use_scm_version={"fallback_version": "0.5.0"},
    setup_requires=["setuptools-scm"],
    author="Paritosh Ramanan",
    author_email="paritosh.ramanan@gmail.com",
    description="Scarlets — Redis-backed distributed shared memory primitives for multi-agent systems",
    long_description=open("README.md").read() if __import__("os").path.exists("README.md") else "",
    long_description_content_type="text/markdown",
    url="https://github.com/disys-lab/scarlet-composer-studio",
    license="Apache-2.0",
    packages=find_packages(include=["scarlets", "scarlets.*"]),
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
    install_requires=[
        "redis>=4.0.0",
        "numpy>=1.24.0",
        "requests>=2.28.0",
    ],
    python_requires=">=3.9",
)
