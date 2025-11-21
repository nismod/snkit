[![Documentation Status](https://readthedocs.org/projects/snkit/badge/?version=latest)](https://snkit.readthedocs.io/en/latest/?badge=latest)
[![Build](https://github.com/tomalrussell/snkit/actions/workflows/test.yml/badge.svg)](https://github.com/tomalrussell/snkit/actions/workflows/test.yml)
[![License](https://img.shields.io/pypi/l/snkit.svg)](https://opensource.org/licenses/MIT)
[![PyPI version](https://img.shields.io/pypi/v/snkit.svg)](https://pypi.org/project/snkit/)
[![DOI](https://zenodo.org/badge/129739785.svg)](https://doi.org/10.5281/zenodo.3269518)
[![Poster](https://img.shields.io/badge/poster-10.6084%2Fm9.figshare.11864826.v1-purple)](https://doi.org/10.6084/m9.figshare.11864826.v1)
[![Conda Forge version](https://anaconda.org/conda-forge/snkit/badges/version.svg)](https://anaconda.org/conda-forge/snkit)

# snkit - a spatial networks toolkit

/ˈsnɪkɪt/ – sounds like [snicket](https://en.oxforddictionaries.com/definition/snicket) (noun,
Northern English) A narrow passage between houses; an alleyway.

## Why use snkit?

`snkit` helps tidy spatial network data.

Say you have some edges and nodes (lines and points, connections and vertices). None of them
are quite connected, and there's no explicit data to define which node is at the end of which
edge, or which edges are connected.

For example:

![Unconnected network](docs/source/_static/unconnected-network.png)

`snkit` has methods to:

- add endpoints to each edge
- connect nodes to nearest edges
- split edges at connecting points
- create node and edge ids, and add from_id and to_id to each edge

### Spatial network

The output of a snkit data cleaning process might look something like this:

![Connected network](docs/source/_static/connected-network.png)

#### Nodes

| geometry            | id     | other attributes... |
| ------------------- | ------ | ------------------- |
| `POINT (0.03 0.04)` | node_0 | ...                 |
| `POINT (0.03 0.03)` | node_1 | ...                 |
| `POINT (0.02 0.03)` | node_2 | ...                 |

#### Edges

| geometry                    | id     | from_id | to_id   | other attributes... |
| --------------------------- | ------ | ------- | ------- | ------------------- |
| `LINESTRING (0.04 -0.04...` | edge_0 | node_10 | node_22 | ...                 |
| `LINESTRING (0.01 -0.03...` | edge_1 | node_22 | node_21 | ...                 |
| `LINESTRING (0.02 -0.02...` | edge_2 | node_21 | node_25 | ...                 |

## Getting started

Install system libraries (only tested on Ubuntu):

    sudo apt-get install -y libgeos-dev gdal-bin

Or use [conda](https://docs.conda.io/en/latest/miniconda.html) to install major dependencies:

    conda install geopandas shapely

Install or upgrade `snkit` using pip:

    pip install --upgrade snkit

See the [demo
notebook](https://github.com/tomalrussell/snkit/blob/master/notebooks/snkit-demo.ipynb) for a
small demonstration.

## Development

Clone this repository:

    git clone git@github.com:tomalrussell/snkit.git

Maybe set up a virtualenv or conda environment, as you wish. Then install `snkit` in editable
mode, with development packages:

    pip install -e .[dev]

Run the tests:

    python -m pytest tests/

### Development checks

Configure the [pre-commit](https://pre-commit.com/) checks:

    pre-commit install

There are several tools and helpers set up to run automatically, on `git commit`
and in [GitHub Actions](https://docs.github.com/en/actions) continuous
integration steps. Each of these can be run locally too.

Run the tests using [pytest](https://docs.pytest.org):

    python -m pytest

Run formatting using [black](https://black.readthedocs.io/):

    black .

Run linting using [ruff](https://docs.astral.sh/ruff/):

    ruff check .

Run type-checking using [mypy](https://mypy.readthedocs.io/):

    mypy --strict .

## Testimonials 💯 👍 😊

> With five lines of snkit I replaced four or five hundred lines of custom code!

A. Contented Customer (@czor847)

## Related projects

- [`pysal/spaghetti`](https://pysal-spaghetti.readthedocs.io/en/latest/index.html) has methods
  for building graph-theoretic networks and the analysis of network events; JOSS paper [10.21105/joss.02826](https://doi.org/10.21105/joss.02826) cites `snkit`
- [`osmnx`](https://osmnx.readthedocs.io/en/stable/) lets you retrieve, model, analyze, and
  visualize street networks from OpenStreetMap, including methods to correct and simplify
  network topology.
- [`neatnet`](https://github.com/uscuni/neatnet) focuses on simplification of street networks; CEUS paper [10.1016/j.compenvurbsys.2025.102354](https://doi.org/10.1016/j.compenvurbsys.2025.102354) cites `snkit`

## Acknowledgements

```
MIT License

Copyright (c) 2018 Tom Russell and snkit contributors
```

Initial snkit development was at the [Environmental Change Institute, University of
Oxford](http://www.eci.ox.ac.uk/) within the EPSRC sponsored MISTRAL programme, as part of the
[Infrastructure Transition Research Consortium](http://www.itrc.org.uk/).
