//! The snkit kernel for JavaScript.
//!
//! One function, `call`, reaches every function of the kernel by name. It
//! takes an object of named arguments and gives back an object of named
//! results; arrays cross as typed arrays, with no copy through JavaScript
//! values. See `README.md` beside this crate.

use js_sys::{Array, Float64Array, Int32Array, Object, Reflect, Uint8Array};
use snkit_kernel::dispatch::{self, Arguments, Value};
use wasm_bindgen::prelude::*;

/// One argument, from JavaScript. `None` for null or undefined, which mean "left out".
fn argument(name: &str, value: &JsValue) -> Result<Option<Value>, JsError> {
    if value.is_null() || value.is_undefined() {
        return Ok(None);
    }
    if let Some(number) = value.as_f64() {
        return Ok(Some(Value::Number(number)));
    }
    if let Some(flag) = value.as_bool() {
        return Ok(Some(Value::Bool(flag)));
    }
    if let Some(array) = value.dyn_ref::<Float64Array>() {
        return Ok(Some(Value::Floats(array.to_vec())));
    }
    if let Some(array) = value.dyn_ref::<Int32Array>() {
        return Ok(Some(Value::Ints(array.to_vec().into_iter().map(i64::from).collect())));
    }
    if let Some(array) = value.dyn_ref::<Uint8Array>() {
        return Ok(Some(Value::Bools(array.to_vec().into_iter().map(|b| b != 0).collect())));
    }
    if let Some(array) = value.dyn_ref::<Array>() {
        // a plain array of numbers or of booleans; coordinates may be given as pairs
        let flat = array.flat(1);
        if flat.length() > 0 && flat.iter().all(|item| item.as_bool().is_some()) {
            return Ok(Some(Value::Bools(flat.iter().map(|item| item.as_bool().unwrap()).collect())));
        }
        let numbers: Option<Vec<f64>> = flat.iter().map(|item| item.as_f64()).collect();
        if let Some(numbers) = numbers {
            return Ok(Some(Value::Floats(numbers)));
        }
    }
    Err(JsError::new(&format!(
        "argument '{name}' must be a number, a boolean, a Float64Array, an Int32Array or an array of numbers"
    )))
}

/// One result, for JavaScript.
fn result(name: &str, value: Value) -> Result<JsValue, JsError> {
    Ok(match value {
        Value::Number(number) => JsValue::from_f64(number),
        Value::Bool(flag) => JsValue::from_bool(flag),
        Value::Floats(values) | Value::Points(values) => Float64Array::from(&values[..]).into(),
        Value::Bools(values) => {
            Uint8Array::from(&values.into_iter().map(u8::from).collect::<Vec<_>>()[..]).into()
        }
        Value::Ints(values) => {
            let narrow: Result<Vec<i32>, _> = values.into_iter().map(i32::try_from).collect();
            let narrow = narrow.map_err(|_| JsError::new(&format!("result '{name}' has a position beyond 2^31")))?;
            Int32Array::from(&narrow[..]).into()
        }
    })
}

/// Call a function of the kernel by name.
///
/// `args` is an object of named arguments. Arrays of positions are
/// `Int32Array`; arrays of distances are `Float64Array`; coordinates are a
/// `Float64Array` of `x0, y0, x1, y1, ...`. Plain arrays of numbers are
/// accepted too. The result is an object of named typed arrays, with
/// true-or-false arrays as `Uint8Array`.
#[wasm_bindgen]
pub fn call(function: &str, args: &JsValue) -> Result<JsValue, JsError> {
    let mut arguments = Arguments::new();
    if !args.is_null() && !args.is_undefined() {
        let object: &Object = args.dyn_ref().ok_or_else(|| JsError::new("arguments must be an object"))?;
        for entry in Object::entries(object).iter() {
            let entry: Array = entry.into();
            let name = entry.get(0).as_string().unwrap_or_default();
            if let Some(value) = argument(&name, &entry.get(1))? {
                arguments.insert(name, value);
            }
        }
    }
    let results = dispatch::call(function, &arguments).map_err(|message| JsError::new(&message))?;
    let out = Object::new();
    for (name, value) in results {
        Reflect::set(&out, &JsValue::from_str(name), &result(name, value)?)
            .map_err(|_| JsError::new("could not build the result"))?;
    }
    Ok(out.into())
}

/// The names of the functions that `call` knows.
#[wasm_bindgen]
pub fn functions() -> Vec<String> {
    dispatch::FUNCTIONS.iter().map(|name| name.to_string()).collect()
}
