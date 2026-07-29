# gpu-exporter.ps1 — serve nvidia-smi as Prometheus metrics on :9106 (Windows).
#
# Counterpart of scripts/ollama-exporter.py for the gaming rig: the Pi
# wallboard's Prometheus scrapes it as job `gpu-windows` so the kiosk's GPU
# panels show this machine's load alongside the Linux workstation's.
#
# Raw TcpListener rather than HttpListener on purpose — HttpListener needs a
# urlacl reservation for non-localhost prefixes; a hand-rolled HTTP/1.1
# response needs nothing. Install (elevated PowerShell; writes this file to
# C:\ProgramData\jobcontext\, adds a firewall allow on 9106, registers a
# logon scheduled task): see the block in scripts/gpu-exporter-install.txt.

$ErrorActionPreference = 'SilentlyContinue'
$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Any, 9106)
$listener.Start()

while ($true) {
    $client = $listener.AcceptTcpClient()
    try {
        $stream = $client.GetStream()
        $stream.ReadTimeout = 3000
        $reader = New-Object System.IO.StreamReader($stream)
        while (($line = $reader.ReadLine()) -and $line -ne '') { }  # drain request

        $lines = @(
            '# TYPE gpu_utilization_percent gauge'
            '# TYPE gpu_memory_used_bytes gauge'
            '# TYPE gpu_memory_total_bytes gauge'
            '# TYPE gpu_temperature_celsius gauge'
        )
        $rows = & nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits
        $i = 0
        foreach ($row in $rows) {
            $f = $row -split ',' | ForEach-Object { $_.Trim() }
            if ($f.Count -ge 4) {
                $lines += "gpu_utilization_percent{gpu=`"$i`"} $($f[0])"
                $lines += "gpu_memory_used_bytes{gpu=`"$i`"} $([long]$f[1] * 1048576)"
                $lines += "gpu_memory_total_bytes{gpu=`"$i`"} $([long]$f[2] * 1048576)"
                $lines += "gpu_temperature_celsius{gpu=`"$i`"} $($f[3])"
            }
            $i++
        }
        $body = [System.Text.Encoding]::UTF8.GetBytes(($lines -join "`n") + "`n")
        $head = "HTTP/1.1 200 OK`r`nContent-Type: text/plain; version=0.0.4`r`nContent-Length: $($body.Length)`r`nConnection: close`r`n`r`n"
        $headBytes = [System.Text.Encoding]::ASCII.GetBytes($head)
        $stream.Write($headBytes, 0, $headBytes.Length)
        $stream.Write($body, 0, $body.Length)
        $stream.Flush()
    } catch { } finally { $client.Close() }
}
