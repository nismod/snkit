#' Call a function of the snkit kernel
#'
#' Every function of the kernel is reached by name. Arguments and results
#' are plain vectors, with the names given in the kernel's conformance cases
#' (`conformance/README.md` in the snkit repository).
#'
#' Coordinates are matrices of two columns, x and y, one row for each point.
#' A set of lines is `coords`, the vertices of all lines one after another,
#' and `offsets`, with one more entry than there are lines.
#'
#' Positions count from 0, as they do in the kernel and in every other
#' language it is used from: the first vertex is vertex 0.
#'
#' @param .function The name of the function; see [snkit_functions()]. (The
#'   dot keeps it apart from the kernel's own arguments, one of which is `n`.)
#' @param ... Its arguments, by name.
#' @return A named list of vectors. Coordinates are matrices of two columns.
#' @examples
#' # two lines that cross at (1, 1)
#' coords <- rbind(c(0, 0), c(2, 2), c(0, 2), c(2, 0))
#' snkit_call("segment_crossings", coords = coords, offsets = c(0, 2, 4))$xy
#' @export
snkit_call <- function(.function, ...) {
  args <- lapply(list(...), function(arg) {
    # a matrix of coordinates goes in a row at a time: x0, y0, x1, y1, ...
    if (is.matrix(arg)) as.double(t(arg)) else arg
  })
  args <- args[!vapply(args, is.null, logical(1))]
  result <- .Call(wrap__snkit_call, .function, args)
  lapply(result, function(value) {
    if (isTRUE(attr(value, "points"))) {
      matrix(as.double(value), ncol = 2, byrow = TRUE)
    } else {
      value
    }
  })
}

#' The names of the functions of the kernel
#' @return A character vector.
#' @export
snkit_functions <- function() .Call(wrap__snkit_functions)
