// R looks for R_init_<package> in the shared library; the routines are
// registered on the Rust side.
void R_init_snkit_extendr(void *dll);

void R_init_snkit(void *dll) {
    R_init_snkit_extendr(dll);
}
