# gpu-exporter.ps1 — serve nvidia-smi + local-LLM metrics on :9106 (Windows).
#
# Counterpart of scripts/ollama-exporter.py for the Windows boot: the Pi
# wallboard's Prometheus scrapes it as job `gpu-windows` so the kiosk's GPU
# panels show this machine's load alongside the Linux workstation's. Since
# the Windows boot also runs llama-server (:8081, setup-llama-windows.ps1),
# it additionally emits the same local_llm_* series the Linux exporter does,
# plus llama.cpp's native llamacpp:* families relayed verbatim — so the
# kiosk local-LLM board works under either boot.
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
        # BOTH directions get timeouts. The read timeout was here from day
        # one; the missing WRITE timeout wedged the exporter on 2026-08-11: a
        # scrape connection went half-dead during a LAN renumbering, Write()
        # blocked forever on a full send buffer, and — this loop being
        # single-threaded — every later connection (including localhost)
        # timed out in the backlog while the task still showed "Running".
        $client.ReceiveTimeout = 3000
        $client.SendTimeout = 3000
        $stream = $client.GetStream()
        $stream.ReadTimeout = 3000
        $stream.WriteTimeout = 3000
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

        # Local LLM (llama-server :8081 with --metrics). Same truthfulness
        # contract as the Linux exporter: local_llm_up is always 0/1 while
        # this exporter is alive; what a probe can't observe is ABSENT,
        # never 0. -ErrorAction Stop is load-bearing — the script-global
        # SilentlyContinue would otherwise skip the catch and emit neither.
        $lines += '# TYPE local_llm_up gauge'
        try {
            $props = Invoke-RestMethod 'http://127.0.0.1:8081/props' -TimeoutSec 2 -ErrorAction Stop
            $lines += 'local_llm_up 1'
            $model = if ($props.model_alias) { $props.model_alias } else { 'unknown' }
            $lines += '# TYPE local_llm_info gauge'
            $lines += "local_llm_info{server=`"llama.cpp`",model=`"$model`",ftype=`"$($props.model_ftype)`"} 1"
            $nctx = $props.default_generation_settings.n_ctx
            if ($nctx) {
                $lines += '# TYPE local_llm_context_length gauge'
                $lines += "local_llm_context_length $nctx"
            }
            try {
                $mdl = Invoke-RestMethod 'http://127.0.0.1:8081/v1/models' -TimeoutSec 2 -ErrorAction Stop
                $size = $mdl.data[0].meta.size
                if ($size) {
                    $lines += '# TYPE local_llm_model_size_bytes gauge'
                    $lines += "local_llm_model_size_bytes{model=`"$model`"} $size"
                }
            } catch { }
            try {
                # Native Prometheus counters, relayed verbatim so the Pi's
                # rate()/increase() see true monotonic series.
                $met = (Invoke-WebRequest 'http://127.0.0.1:8081/metrics' -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop).Content
                $lines += ($met -split "`n") | ForEach-Object { $_.TrimEnd("`r") } | Where-Object {
                    $_ -match '^llamacpp:' -or $_ -match '^# (TYPE|HELP) llamacpp:' }
            } catch { }
        } catch {
            $lines += 'local_llm_up 0'
        }

        $body = [System.Text.Encoding]::UTF8.GetBytes(($lines -join "`n") + "`n")
        $head = "HTTP/1.1 200 OK`r`nContent-Type: text/plain; version=0.0.4`r`nContent-Length: $($body.Length)`r`nConnection: close`r`n`r`n"
        $headBytes = [System.Text.Encoding]::ASCII.GetBytes($head)
        $stream.Write($headBytes, 0, $headBytes.Length)
        $stream.Write($body, 0, $body.Length)
        $stream.Flush()
    } catch { } finally { $client.Close() }
}
