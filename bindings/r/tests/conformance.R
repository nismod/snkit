# Run the kernel-tier conformance cases (conformance/kernel at the top of the
# snkit repository) against this package. Set SNKIT_CONFORMANCE to that
# directory; without it, or without jsonlite, only a small check is run.

library(snkit)

coords <- rbind(c(0, 0), c(2, 2), c(0, 2), c(2, 0))
found <- snkit_call("segment_crossings", coords = coords, offsets = c(0, 2, 4))
stopifnot(identical(found$xy, matrix(c(1, 1), ncol = 2)), identical(found$seg_a, 0L))
stopifnot(inherits(try(snkit_call("no_such_function"), silent = TRUE), "try-error"))
stopifnot(inherits(try(snkit_call("point_pairs", tolerance = 1), silent = TRUE), "try-error"))

root <- Sys.getenv("SNKIT_CONFORMANCE")
if (nzchar(root) && requireNamespace("jsonlite", quietly = TRUE)) {
  files <- list.files(root, pattern = "\\.json$", recursive = TRUE, full.names = TRUE)
  stopifnot(length(files) >= 40)
  covered <- character()
  for (file in files) {
    case <- jsonlite::fromJSON(file, simplifyVector = TRUE)
    # an empty JSON array is read as an empty list: make it an empty vector
    input <- lapply(case$input, function(value) if (is.list(value)) numeric() else value)
    result <- do.call(snkit_call, c(list(case[["function"]]), input))
    stopifnot(setequal(names(result), names(case$expected)))
    for (name in names(case$expected)) {
      want <- case$expected[[name]]
      # coordinates are matrices on both sides; compare row by row
      want <- if (is.list(want)) numeric() else as.double(t(want))
      got <- as.double(t(result[[name]]))
      if (length(got) != length(want) || any(abs(got - want) > 1e-9)) {
        stop(sprintf("%s: '%s' is %s, expected %s", file, name, toString(got), toString(want)))
      }
    }
    covered <- c(covered, case[["function"]])
  }
  stopifnot(setequal(covered, snkit_functions()))
  cat(length(files), "conformance cases passed\n")
}
