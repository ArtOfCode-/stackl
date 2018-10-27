import setuptools
import stackl

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="stackl",
    version=stackl.VERSION,
    author="ArtOfCode",
    author_email="hello@artofcode.co.uk",
    description="Python library for connecting to Stack Exchange chat",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/ArtOfCode-/stackl",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
