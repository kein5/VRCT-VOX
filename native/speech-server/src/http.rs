//! A bounded HTTP/1.1 client for the numeric loopback address only.
//!
//! Every request has one deadline for the connect, the headers and the body, and can be
//! interrupted from another thread. Bodies are never logged or put into an error.

use std::io::{self, Read, Write};
use std::net::{Ipv4Addr, Shutdown, SocketAddr, TcpStream};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::Instant;

/// Stops a request that is in flight, and any request begun after it.
#[derive(Default)]
pub struct Cancel {
    set: AtomicBool,
    socket: Mutex<Option<TcpStream>>,
}

impl Cancel {
    pub fn new() -> Cancel {
        Cancel::default()
    }

    pub fn cancel(&self) {
        self.set.store(true, Ordering::SeqCst);
        if let Some(socket) = self.socket.lock().unwrap().take() {
            // shutdown wakes a blocked read without closing the reader's descriptor.
            let _ = socket.shutdown(Shutdown::Both);
        }
    }

    pub fn is_set(&self) -> bool {
        self.set.load(Ordering::SeqCst)
    }

    fn register(&self, stream: &TcpStream) -> io::Result<()> {
        *self.socket.lock().unwrap() = Some(stream.try_clone()?);
        if self.is_set() {
            self.cancel();
            return Err(io::ErrorKind::Interrupted.into());
        }
        Ok(())
    }
}

pub(crate) enum Body {
    /// Keep the body; one longer than this many bytes is an error.
    Keep(usize),
    /// Read the body to its end and throw it away.
    Discard,
}

pub(crate) struct Response {
    pub status: u16,
    pub body: Vec<u8>,
}

fn timed_out() -> io::Error {
    io::ErrorKind::TimedOut.into()
}

fn invalid() -> io::Error {
    io::ErrorKind::InvalidData.into()
}

fn read_some(stream: &mut TcpStream, buffer: &mut [u8], deadline: Instant) -> io::Result<usize> {
    let remaining = deadline.checked_duration_since(Instant::now()).filter(|d| !d.is_zero()).ok_or_else(timed_out)?;
    stream.set_read_timeout(Some(remaining))?;
    match stream.read(buffer) {
        Err(error) if matches!(error.kind(), io::ErrorKind::WouldBlock | io::ErrorKind::TimedOut) => Err(timed_out()),
        other => other,
    }
}

fn header<'a>(head: &'a str, name: &str) -> Option<&'a str> {
    head.split("\r\n").skip(1).find_map(|line| {
        let (key, value) = line.split_once(':')?;
        key.trim().eq_ignore_ascii_case(name).then(|| value.trim())
    })
}

/// The payload of a chunked body, or None while its last chunk has not arrived.
fn dechunk(mut raw: &[u8]) -> io::Result<Option<Vec<u8>>> {
    let mut body = Vec::new();
    loop {
        let Some(line_end) = raw.windows(2).position(|pair| pair == b"\r\n") else { return Ok(None) };
        let line = std::str::from_utf8(&raw[..line_end]).map_err(|_| invalid())?;
        let size = usize::from_str_radix(line.split(';').next().unwrap_or("").trim(), 16).map_err(|_| invalid())?;
        raw = &raw[line_end + 2..];
        if size == 0 {
            return Ok(Some(body));
        }
        if raw.len() < size + 2 {
            return Ok(None);
        }
        body.extend_from_slice(&raw[..size]);
        raw = &raw[size + 2..];
    }
}

/// One request to `127.0.0.1:port`. `content` is the content type and the body to send.
pub(crate) fn request(
    port: u16,
    method: &str,
    path: &str,
    content: Option<(&str, &[u8])>,
    keep: Body,
    deadline: Instant,
    cancel: Option<&Cancel>,
) -> io::Result<Response> {
    let remaining = deadline.checked_duration_since(Instant::now()).filter(|d| !d.is_zero()).ok_or_else(timed_out)?;
    if cancel.is_some_and(Cancel::is_set) {
        return Err(io::ErrorKind::Interrupted.into());
    }
    let address = SocketAddr::from((Ipv4Addr::LOCALHOST, port));
    let mut stream = TcpStream::connect_timeout(&address, remaining)?;
    if let Some(cancel) = cancel {
        cancel.register(&stream)?;
    }
    let remaining = deadline.checked_duration_since(Instant::now()).filter(|d| !d.is_zero()).ok_or_else(timed_out)?;
    stream.set_write_timeout(Some(remaining))?;
    let mut head = format!("{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n");
    if let Some((kind, body)) = content {
        head += &format!("Content-Type: {kind}\r\nContent-Length: {}\r\n", body.len());
    }
    head += "\r\n";
    stream.write_all(head.as_bytes())?;
    if let Some((_, body)) = content {
        stream.write_all(body)?;
    }

    let mut received = Vec::new();
    let mut block = [0u8; 16384];
    let head_end = loop {
        if let Some(end) = received.windows(4).position(|four| four == b"\r\n\r\n") {
            break end;
        }
        if received.len() > 65536 {
            return Err(invalid());
        }
        let read = read_some(&mut stream, &mut block, deadline)?;
        if read == 0 {
            return Err(io::ErrorKind::UnexpectedEof.into());
        }
        received.extend_from_slice(&block[..read]);
    };
    let head = std::str::from_utf8(&received[..head_end]).map_err(|_| invalid())?.to_owned();
    let status: u16 = head.split(' ').nth(1).and_then(|code| code.parse().ok()).ok_or_else(invalid)?;
    let chunked = header(&head, "transfer-encoding").is_some_and(|value| value.eq_ignore_ascii_case("chunked"));
    let length: Option<usize> = match header(&head, "content-length") {
        Some(value) if !chunked => Some(value.parse().map_err(|_| invalid())?),
        _ => None,
    };
    let mut raw = received.split_off(head_end + 4);

    match keep {
        Body::Keep(limit) => {
            // The framing of a chunked body costs a little more than its payload.
            let raw_limit = if chunked { limit.saturating_mul(2).saturating_add(4096) } else { limit };
            if length.is_some_and(|length| length > limit) {
                return Err(invalid());
            }
            loop {
                if raw.len() > raw_limit {
                    return Err(invalid());
                }
                if length.is_some_and(|length| raw.len() >= length) {
                    raw.truncate(length.unwrap_or(0));
                    break;
                }
                if chunked {
                    if let Some(body) = dechunk(&raw)? {
                        raw = body;
                        break;
                    }
                }
                let read = read_some(&mut stream, &mut block, deadline)?;
                if read == 0 {
                    if length.is_some() || chunked {
                        return Err(io::ErrorKind::UnexpectedEof.into());
                    }
                    break;
                }
                raw.extend_from_slice(&block[..read]);
            }
            if raw.len() > limit {
                return Err(invalid());
            }
            Ok(Response { status, body: raw })
        }
        Body::Discard => {
            let mut seen = raw.len();
            let mut tail: Vec<u8> = raw.iter().rev().take(5).rev().copied().collect();
            loop {
                if length.is_some_and(|length| seen >= length) || (chunked && tail == b"0\r\n\r\n") {
                    break;
                }
                let read = read_some(&mut stream, &mut block, deadline)?;
                if read == 0 {
                    break;
                }
                seen += read;
                tail.extend_from_slice(&block[..read]);
                let extra = tail.len().saturating_sub(5);
                tail.drain(..extra);
            }
            Ok(Response { status, body: Vec::new() })
        }
    }
}
