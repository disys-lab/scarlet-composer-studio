from setuptools import setup, find_packages

setup(
    name="data-connectors",
    use_scm_version={"fallback_version": "0.1.0"},
    setup_requires=["setuptools-scm"],
    author="Paritosh Ramanan",
    author_email="paritosh.ramanan@gmail.com",
    description="Pluggable data-source connectors (mssql, postgres, mysql, pi, influx, redis) - shared by the broker and any in-process caller (e.g. scarlet-agentic-harness's local-mode data sources).",
    long_description=open("README.md").read() if __import__("os").path.exists("README.md") else "",
    long_description_content_type="text/markdown",
    url="https://github.com/disys-lab/scarlet-composer-studio",
    license="Apache-2.0",
    packages=find_packages(include=["data_connectors", "data_connectors.*"]),
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
    install_requires=[
        # mssql - needs the system-level ODBC Driver 18 for SQL Server +
        # Kerberos client tooling too (see broker/Dockerfile), not just
        # this package.
        "pyodbc>=5.1.0",
        # pi - the real pitalk package (github.com/blockalytics/PITalk) is
        # installed separately, with --no-deps, wherever this package is
        # deployed (its own setup.py pins versions with no installable
        # wheel for a modern Python) - these are its actual runtime deps.
        "pandas>=2.0.0",
        "pyyaml>=6.0",
        "requests-kerberos>=0.15.0",
        # influx - InfluxDB 1.x's DataFrameClient (InfluxQL), not the 2.x
        # influxdb-client package.
        "influxdb>=5.3.0",
        # postgres - psycopg2-binary bundles its own libpq.
        "psycopg2-binary>=2.9.0",
        # mysql - PyMySQL is pure Python, no system dependency.
        "pymysql>=1.1.0",
        # redis
        "redis>=5.0.0",
        # shared by every connector's query()
        "requests>=2.28.0",
    ],
    python_requires=">=3.10",
)
