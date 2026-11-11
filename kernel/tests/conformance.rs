//! Run the kernel-tier conformance cases (`conformance/kernel` at the top of
//! the repository) through `dispatch::call`, as a binding to another language would.

use std::fs;
use std::path::Path;

use serde_json::Value as Json;
use snkit_kernel::dispatch::{call, Arguments, Value, FUNCTIONS};

/// A JSON argument as the kernel takes it. Coordinates, `[[x, y], ...]`, are interleaved.
fn argument(json: &Json) -> Option<Value> {
    Some(match json {
        Json::Null => return None,
        Json::Bool(b) => Value::Bool(*b),
        Json::Number(n) => Value::Number(n.as_f64().unwrap()),
        Json::Array(items) if items.iter().any(Json::is_array) => Value::Points(
            items
                .iter()
                .flat_map(|p| p.as_array().unwrap())
                .map(|v| v.as_f64().unwrap())
                .collect(),
        ),
        Json::Array(items) if !items.is_empty() && items.iter().all(Json::is_boolean) => {
            Value::Bools(items.iter().map(|v| v.as_bool().unwrap()).collect())
        }
        Json::Array(items) => Value::Floats(items.iter().map(|v| v.as_f64().unwrap()).collect()),
        other => panic!("unexpected argument {other}"),
    })
}

/// Any value as plain numbers, for comparing.
fn numbers(value: &Value) -> Vec<f64> {
    match value {
        Value::Number(x) => vec![*x],
        Value::Bool(b) => vec![f64::from(*b)],
        Value::Ints(v) => v.iter().map(|&x| x as f64).collect(),
        Value::Floats(v) | Value::Points(v) => v.clone(),
        Value::Bools(v) => v.iter().map(|&b| f64::from(b)).collect(),
    }
}

#[test]
fn kernel_cases() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../conformance/kernel");
    let mut covered = Vec::new();
    let mut count = 0;
    for folder in fs::read_dir(&root).unwrap() {
        for file in fs::read_dir(folder.unwrap().path()).unwrap() {
            let path = file.unwrap().path();
            let case: Json = serde_json::from_str(&fs::read_to_string(&path).unwrap()).unwrap();
            let function = case["function"].as_str().unwrap();
            let arguments: Arguments = case["input"]
                .as_object()
                .unwrap()
                .iter()
                .filter_map(|(name, json)| argument(json).map(|value| (name.clone(), value)))
                .collect();
            let results = call(function, &arguments).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
            let expected = case["expected"].as_object().unwrap();
            assert_eq!(results.len(), expected.len(), "{}: number of outputs", path.display());
            for (name, value) in &results {
                let want = numbers(&argument(&expected[*name]).unwrap_or(Value::Floats(vec![])));
                let got = numbers(value);
                assert_eq!(got.len(), want.len(), "{}: length of '{name}'", path.display());
                for (g, w) in got.iter().zip(&want) {
                    assert!(
                        (g - w).abs() <= 1e-9,
                        "{}: '{name}' is {got:?}, expected {want:?}",
                        path.display()
                    );
                }
            }
            covered.push(function.to_string());
            count += 1;
        }
    }
    assert!(count >= 40, "only {count} cases found");
    for function in FUNCTIONS {
        assert!(covered.iter().any(|f| f == function), "no case for '{function}'");
    }
}

#[test]
fn mistakes_are_reported_not_fatal() {
    assert!(call("no_such_function", &Arguments::new())
        .unwrap_err()
        .contains("no function"));
    assert!(call("point_pairs", &Arguments::new())
        .unwrap_err()
        .contains("missing argument 'xy'"));
    let mut bad = Arguments::new();
    bad.insert("coords".into(), Value::Points(vec![0.0, 0.0, 1.0, 1.0]));
    bad.insert("offsets".into(), Value::Ints(vec![0, 5]));
    assert!(call("line_measures", &bad).unwrap_err().contains("offsets"));
}
