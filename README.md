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

Maybe set up a virtualenv or conda environment, as you wish. Install a
[Rust toolchain](https://rustup.rs), which is needed to build the kernel. Then install
`snkit` in editable mode, with development packages:

    pip install -e .[dev]

Run that again after changing any Rust code in `kernel/`.

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

Run formatting and linting using [ruff](https://docs.astral.sh/ruff/):

    ruff format
    ruff check

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

## Network operations API

`snkit` also has a newer set of functions, available directly as `snkit.<function>`, which
keep a network's topology exact at every step: ids are integers, every edge names its end
nodes, and edge geometries end precisely on them.

```python
import geopandas
import snkit
from shapely import LineString, Point

roads = geopandas.GeoDataFrame(
    {"name": ["High St", "Mill Lane"]},
    geometry=[LineString([(0, 0), (10, 0)]), LineString([(5, -5), (5, 5)])],
    crs="EPSG:27700",
)
depots = geopandas.GeoDataFrame({"depot": ["north"]}, geometry=[Point(8, 2)], crs="EPSG:27700")

network = snkit.from_nodes_and_edges(depots, roads)   # nodes at line ends, ids, from/to
network = snkit.split_edges_at_crossings(network)     # a junction where the roads cross
network = snkit.link_nodes_to_edges(network)          # connect the depot to the nearest road
```

```
   id  from_id  to_id       name                geometry
0   2        1      5    High St   LINESTRING (0 0, 5 0)
1   6        5      6    High St   LINESTRING (5 0, 8 0)
2   7        6      2    High St  LINESTRING (8 0, 10 0)
3   4        3      5  Mill Lane  LINESTRING (5 -5, 5 0)
4   5        5      4  Mill Lane   LINESTRING (5 0, 5 5)
5   8        0      6        NaN   LINESTRING (8 2, 8 0)
```

| To... | Use |
| --- | --- |
| build a network | `from_edges`, `from_nodes_and_edges`, `from_topology`, `validate` |
| look before changing anything | `match_nodes`, `match_nodes_to_edges`, `find_crossings`, `match_edges` |
| join things up | `merge_nodes`, `link_nodes`, `link_nodes_to_edges`, `split_edges_at_nodes`, `split_edges_at_crossings` |
| tidy | `merge_edges`, `simplify_edges`, `drop_duplicate_edges`, `label_components` |
| work with several networks | `combine`, `stitch`, `union`, `intersection`, `difference` |
| work at scale | `to_arrays`, `ArrayNetwork`, `snkit.io.read`, `read_network`, `build_network` |

These functions, and the older ones in `snkit.network`, run on a kernel written in Rust
that works on plain arrays and is compiled into the package ([`kernel/`](kernel/README.md)).

For a large network, hold geometry in arrays instead of GeoDataFrames by starting from
Arrow data, and read and write files without a geometry object per feature
(`pip install snkit[arrow]`):

```python
import snkit.io

network = snkit.from_edges(snkit.io.read("roads.gpkg"))   # an ArrayNetwork
network = snkit.split_edges_at_crossings(network)
network.to_parquet("nodes.parquet", "edges.parquet")
```

For a network too large for memory, build it tile by tile, from file to file:

```python
built = snkit.build_network("roads.parquet", "network/", max_tile_edges=250_000)
part = built.read(bbox=(430000, 420000, 440000, 430000))   # one area, into memory
```

The source can be GeoParquet, any format GDAL reads, or the result of a query in an engine
such as SedonaDB or DuckDB.

Each function's documentation has a small example. The
[design document](docs/source/design.md) explains the ideas, with a worked example of every
operation.
