"""snkit - a spatial networks toolkit"""

from importlib.metadata import version, PackageNotFoundError

# Define what is accessible directly on snkit, when a client writes::
#   from snkit import Network
from snkit.network import Network
from snkit.arrays import ArrayNetwork, to_arrays
from snkit.core import (
    Lineage,
    from_edges,
    from_nodes_and_edges,
    from_topology,
    validate,
)
from snkit.match import (
    find_crossings,
    match_edges,
    match_nodes,
    match_nodes_to_edges,
)
from snkit.operations import (
    drop_duplicate_edges,
    label_components,
    link_nodes,
    link_nodes_to_edges,
    merge_edges,
    merge_nodes,
    simplify_edges,
    split_edges,
    split_edges_at_crossings,
    split_edges_at_nodes,
)
from snkit.multi import combine, difference, intersection, stitch, union
from snkit.io import read_network

__author__ = "Tom Russell"
__copyright__ = "Tom Russell"
__license__ = "mit"


try:
    __version__ = version(__name__)
except (PackageNotFoundError, ValueError):
    __version__ = "unknown"


# Define what should be imported as * when a client writes::
#   from snkit import *
__all__ = [
    "ArrayNetwork",
    "read_network",
    "to_arrays",
    "Lineage",
    "Network",
    "combine",
    "difference",
    "drop_duplicate_edges",
    "find_crossings",
    "from_edges",
    "from_nodes_and_edges",
    "from_topology",
    "intersection",
    "label_components",
    "link_nodes",
    "link_nodes_to_edges",
    "match_edges",
    "match_nodes",
    "match_nodes_to_edges",
    "merge_edges",
    "merge_nodes",
    "simplify_edges",
    "split_edges",
    "split_edges_at_crossings",
    "split_edges_at_nodes",
    "stitch",
    "union",
    "validate",
]
