//! The snkit kernel for R.
//!
//! One routine, `snkit_call`, reaches every function of the kernel by name,
//! taking a named list of vectors and giving one back. The R function of the
//! same name (in `R/snkit.R`) turns matrices of coordinates to and from the
//! interleaved form used here.

use extendr_api::prelude::*;
use snkit_kernel::dispatch::{self, Arguments, Value};

type Result<T> = std::result::Result<T, Error>;

fn argument(name: &str, value: &Robj) -> Result<Value> {
    if let Some(numbers) = value.as_real_vector() {
        return Ok(Value::Floats(numbers));
    }
    if let Some(numbers) = value.as_integer_vector() {
        return Ok(Value::Ints(numbers.into_iter().map(i64::from).collect()));
    }
    if let Some(flags) = value.as_logical_vector() {
        return Ok(Value::Bools(flags.into_iter().map(|flag| flag.is_true()).collect()));
    }
    Err(Error::Other(format!("argument '{name}' must be a numeric, integer or logical vector")))
}

fn result(name: &str, value: Value) -> Result<Robj> {
    Ok(match value {
        Value::Number(number) => r!(number),
        Value::Bool(flag) => r!(flag),
        Value::Floats(values) => r!(values),
        Value::Bools(values) => r!(values),
        Value::Points(values) => {
            // marked, for the R side to shape into a matrix of two columns
            let mut out = r!(values);
            out.set_attrib("points", r!(true))?;
            out
        }
        Value::Ints(values) => {
            let narrow: std::result::Result<Vec<i32>, std::num::TryFromIntError> = values.into_iter().map(i32::try_from).collect();
            r!(narrow.map_err(|_| Error::Other(format!("result '{name}' has a position beyond 2^31")))?)
        }
    })
}

/// Call a function of the kernel by name, with a named list of arguments.
/// @noRd
#[extendr]
fn snkit_call(function: &str, args: List) -> Result<List> {
    let mut arguments = Arguments::new();
    for (name, value) in args.iter() {
        if name.is_empty() {
            return Err(Error::Other("every argument must be named".to_string()));
        }
        arguments.insert(name.to_string(), argument(name, &value)?);
    }
    let results = dispatch::call(function, &arguments).map_err(Error::Other)?;
    let mut names = Vec::new();
    let mut values = Vec::new();
    for (name, value) in results {
        names.push(name);
        values.push(result(name, value)?);
    }
    List::from_names_and_values(names, values)
}

/// The names of the functions that `snkit_call` knows.
/// @noRd
#[extendr]
fn snkit_functions() -> Vec<String> {
    dispatch::FUNCTIONS.iter().map(|name| name.to_string()).collect()
}

extendr_module! {
    mod snkit;
    fn snkit_call;
    fn snkit_functions;
}
