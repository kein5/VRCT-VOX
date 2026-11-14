//! A minimal writer for ONNX models: just the messages and operators the synthesizer
//! graph needs, serialised with `prost`. Field numbers follow the public `onnx.proto`.

use prost::Message;

#[derive(Clone, PartialEq, Message)]
struct ModelProto {
    #[prost(int64, tag = "1")]
    ir_version: i64,
    #[prost(string, tag = "2")]
    producer_name: String,
    #[prost(message, optional, tag = "7")]
    graph: Option<GraphProto>,
    #[prost(message, repeated, tag = "8")]
    opset_import: Vec<OperatorSetId>,
}

#[derive(Clone, PartialEq, Message)]
struct OperatorSetId {
    #[prost(string, tag = "1")]
    domain: String,
    #[prost(int64, tag = "2")]
    version: i64,
}

#[derive(Clone, PartialEq, Message)]
struct GraphProto {
    #[prost(message, repeated, tag = "1")]
    node: Vec<NodeProto>,
    #[prost(string, tag = "2")]
    name: String,
    #[prost(message, repeated, tag = "5")]
    initializer: Vec<TensorProto>,
    #[prost(message, repeated, tag = "11")]
    input: Vec<ValueInfo>,
    #[prost(message, repeated, tag = "12")]
    output: Vec<ValueInfo>,
}

#[derive(Clone, PartialEq, Message)]
struct NodeProto {
    #[prost(string, repeated, tag = "1")]
    input: Vec<String>,
    #[prost(string, repeated, tag = "2")]
    output: Vec<String>,
    #[prost(string, tag = "3")]
    name: String,
    #[prost(string, tag = "4")]
    op_type: String,
    #[prost(message, repeated, tag = "5")]
    attribute: Vec<AttributeProto>,
}

#[derive(Clone, PartialEq, Message)]
struct AttributeProto {
    #[prost(string, tag = "1")]
    name: String,
    #[prost(float, tag = "2")]
    f: f32,
    #[prost(int64, tag = "3")]
    i: i64,
    #[prost(int64, repeated, tag = "8")]
    ints: Vec<i64>,
    #[prost(int32, tag = "20")]
    r#type: i32,
}

#[derive(Clone, PartialEq, Message)]
struct TensorProto {
    #[prost(int64, repeated, tag = "1")]
    dims: Vec<i64>,
    #[prost(int32, tag = "2")]
    data_type: i32,
    #[prost(string, tag = "8")]
    name: String,
    #[prost(bytes = "vec", tag = "9")]
    raw_data: Vec<u8>,
}

#[derive(Clone, PartialEq, Message)]
struct ValueInfo {
    #[prost(string, tag = "1")]
    name: String,
    #[prost(message, optional, tag = "2")]
    r#type: Option<TypeProto>,
}

#[derive(Clone, PartialEq, Message)]
struct TypeProto {
    #[prost(message, optional, tag = "1")]
    tensor_type: Option<TensorType>,
}

#[derive(Clone, PartialEq, Message)]
struct TensorType {
    #[prost(int32, tag = "1")]
    elem_type: i32,
    #[prost(message, optional, tag = "2")]
    shape: Option<ShapeProto>,
}

#[derive(Clone, PartialEq, Message)]
struct ShapeProto {
    #[prost(message, repeated, tag = "1")]
    dim: Vec<Dimension>,
}

#[derive(Clone, PartialEq, Message)]
struct Dimension {
    #[prost(int64, optional, tag = "1")]
    dim_value: Option<i64>,
    #[prost(string, optional, tag = "2")]
    dim_param: Option<String>,
}

const FLOAT: i32 = 1;
const INT64: i32 = 7;

/// An attribute of a node.
pub enum Attr {
    Int(&'static str, i64),
    Float(&'static str, f32),
    Ints(&'static str, Vec<i64>),
}

/// One axis of a graph input or output: a fixed size or a named variable one.
#[derive(Clone, Copy)]
pub enum Dim {
    Fixed(usize),
    Named(&'static str),
}

/// A graph under construction. Values are referred to by name.
#[derive(Default)]
pub struct Graph {
    nodes: Vec<NodeProto>,
    initializers: Vec<TensorProto>,
    inputs: Vec<ValueInfo>,
    outputs: Vec<ValueInfo>,
    counter: usize,
}

impl Graph {
    pub fn new() -> Self {
        Self::default()
    }

    fn fresh(&mut self, hint: &str) -> String {
        self.counter += 1;
        format!("{hint}_{}", self.counter)
    }

    fn value_info(name: &str, elem_type: i32, dims: &[Dim]) -> ValueInfo {
        let dim = dims
            .iter()
            .map(|dim| match dim {
                Dim::Fixed(size) => Dimension { dim_value: Some(*size as i64), dim_param: None },
                Dim::Named(name) => Dimension { dim_value: None, dim_param: Some(name.to_string()) },
            })
            .collect();
        ValueInfo { name: name.to_string(), r#type: Some(TypeProto { tensor_type: Some(TensorType { elem_type, shape: Some(ShapeProto { dim }) }) }) }
    }

    pub fn input_f32(&mut self, name: &str, dims: &[Dim]) -> String {
        self.inputs.push(Self::value_info(name, FLOAT, dims));
        name.to_string()
    }

    pub fn input_i64(&mut self, name: &str, dims: &[Dim]) -> String {
        self.inputs.push(Self::value_info(name, INT64, dims));
        name.to_string()
    }

    /// Declares `value` as a float output called `name`.
    pub fn output_f32(&mut self, name: &str, value: &str, dims: &[Dim]) {
        self.nodes.push(NodeProto { input: vec![value.to_string()], output: vec![name.to_string()], name: format!("out_{name}"), op_type: "Identity".into(), attribute: Vec::new() });
        self.outputs.push(Self::value_info(name, FLOAT, dims));
    }

    /// A constant float tensor.
    pub fn f32s(&mut self, dims: &[usize], data: &[f32]) -> String {
        debug_assert_eq!(dims.iter().product::<usize>(), data.len());
        let name = self.fresh("w");
        let raw_data = data.iter().flat_map(|value| value.to_le_bytes()).collect();
        self.initializers.push(TensorProto { dims: dims.iter().map(|&d| d as i64).collect(), data_type: FLOAT, name: name.clone(), raw_data });
        name
    }

    pub fn scalar(&mut self, value: f32) -> String {
        self.f32s(&[], &[value])
    }

    /// A constant one-dimensional integer tensor (shapes, axes, indices).
    pub fn i64s(&mut self, data: &[i64]) -> String {
        let name = self.fresh("i");
        let raw_data = data.iter().flat_map(|value| value.to_le_bytes()).collect();
        self.initializers.push(TensorProto { dims: vec![data.len() as i64], data_type: INT64, name: name.clone(), raw_data });
        name
    }

    /// Adds a node with one output and returns that output's name.
    pub fn op(&mut self, op_type: &str, inputs: &[&str], attributes: Vec<Attr>) -> String {
        self.op_n(op_type, inputs, attributes, 1).pop().unwrap()
    }

    /// Adds a node with `outputs` outputs.
    pub fn op_n(&mut self, op_type: &str, inputs: &[&str], attributes: Vec<Attr>, outputs: usize) -> Vec<String> {
        let names: Vec<String> = (0..outputs).map(|_| self.fresh("v")).collect();
        let attribute = attributes
            .into_iter()
            .map(|attribute| match attribute {
                Attr::Float(name, f) => AttributeProto { name: name.into(), f, r#type: 1, ..Default::default() },
                Attr::Int(name, i) => AttributeProto { name: name.into(), i, r#type: 2, ..Default::default() },
                Attr::Ints(name, ints) => AttributeProto { name: name.into(), ints, r#type: 7, ..Default::default() },
            })
            .collect();
        let name = self.fresh(op_type);
        self.nodes.push(NodeProto { input: inputs.iter().map(|s| s.to_string()).collect(), output: names.clone(), name, op_type: op_type.into(), attribute });
        names
    }

    // --- shorthand for the operators used more than once -------------------------

    pub fn add(&mut self, a: &str, b: &str) -> String {
        self.op("Add", &[a, b], vec![])
    }

    pub fn sub(&mut self, a: &str, b: &str) -> String {
        self.op("Sub", &[a, b], vec![])
    }

    pub fn mul(&mut self, a: &str, b: &str) -> String {
        self.op("Mul", &[a, b], vec![])
    }

    pub fn matmul(&mut self, a: &str, b: &str) -> String {
        self.op("MatMul", &[a, b], vec![])
    }

    pub fn transpose(&mut self, x: &str, perm: &[i64]) -> String {
        self.op("Transpose", &[x], vec![Attr::Ints("perm", perm.to_vec())])
    }

    pub fn reshape(&mut self, x: &str, shape: &str) -> String {
        self.op("Reshape", &[x, shape], vec![])
    }

    pub fn concat(&mut self, parts: &[&str], axis: i64) -> String {
        self.op("Concat", parts, vec![Attr::Int("axis", axis)])
    }

    pub fn leaky_relu(&mut self, x: &str, slope: f32) -> String {
        self.op("LeakyRelu", &[x], vec![Attr::Float("alpha", slope)])
    }

    /// Zero padding; `pads` is a one-dimensional tensor of all begins then all ends.
    pub fn pad(&mut self, x: &str, pads: &str) -> String {
        self.op("Pad", &[x, pads], vec![])
    }

    /// `x[..., start..end, ...]` along `axes`, with constant bounds.
    pub fn slice(&mut self, x: &str, starts: &[i64], ends: &[i64], axes: &[i64]) -> String {
        let (starts, ends, axes) = (self.i64s(starts), self.i64s(ends), self.i64s(axes));
        self.op("Slice", &[x, &starts, &ends, &axes], vec![])
    }

    /// One-dimensional convolution over `[batch, channels, time]`.
    #[allow(clippy::too_many_arguments)]
    pub fn conv(&mut self, x: &str, weight: &str, bias: Option<&str>, kernel: usize, stride: usize, dilation: usize, pads: (usize, usize)) -> String {
        let mut inputs = vec![x, weight];
        inputs.extend(bias);
        self.op(
            "Conv",
            &inputs,
            vec![
                Attr::Ints("kernel_shape", vec![kernel as i64]),
                Attr::Ints("strides", vec![stride as i64]),
                Attr::Ints("dilations", vec![dilation as i64]),
                Attr::Ints("pads", vec![pads.0 as i64, pads.1 as i64]),
            ],
        )
    }

    pub fn conv_transpose(&mut self, x: &str, weight: &str, bias: Option<&str>, kernel: usize, stride: usize, pad: usize) -> String {
        let mut inputs = vec![x, weight];
        inputs.extend(bias);
        self.op("ConvTranspose", &inputs, vec![Attr::Ints("kernel_shape", vec![kernel as i64]), Attr::Ints("strides", vec![stride as i64]), Attr::Ints("pads", vec![pad as i64, pad as i64])])
    }

    /// Serialises the graph as an ONNX model (opset 17).
    pub fn into_model(self) -> Vec<u8> {
        let graph = GraphProto { node: self.nodes, name: "rvc_synthesizer".into(), initializer: self.initializers, input: self.inputs, output: self.outputs };
        ModelProto { ir_version: 8, producer_name: "rvc-runtime".into(), graph: Some(graph), opset_import: vec![OperatorSetId { domain: String::new(), version: 17 }] }.encode_to_vec()
    }
}
