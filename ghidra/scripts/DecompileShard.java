// Decompile one shard of the program's functions to <outDir>/<addr>.c (reverse-engineering notes, not for redistribution).
// Usage (postScript args): <shardIndex> <shardCount> <outDir> [minBytes=24]
// Functions are sorted by address and dealt round-robin, so shards are balanced. Already-written files are skipped,
// so a crashed or stopped run can simply be restarted.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.util.*;

public class DecompileShard extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        int shard = Integer.parseInt(a[0]), shards = Integer.parseInt(a[1]);
        File outDir = new File(a[2]);
        long minBytes = a.length > 3 ? Long.parseLong(a[3]) : 24;
        outDir.mkdirs();

        List<Function> fns = new ArrayList<>();
        FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
        while (it.hasNext()) {
            Function f = it.next();
            if (f.isThunk() || f.getBody().getNumAddresses() < minBytes) continue;
            fns.add(f);
        }
        println("eligible=" + fns.size() + " shard=" + shard + "/" + shards);

        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        int done = 0, skipped = 0, failed = 0;
        for (int i = shard; i < fns.size(); i += shards) {
            if (monitor.isCancelled()) break;
            Function f = fns.get(i);
            File out = new File(outDir, f.getEntryPoint().toString() + ".c");
            if (out.exists()) { skipped++; continue; }
            DecompileResults r = di.decompileFunction(f, 45, monitor);
            if (!r.decompileCompleted() || r.getDecompiledFunction() == null) { failed++; continue; }
            StringBuilder h = new StringBuilder();
            h.append("// addr=").append(f.getEntryPoint()).append(" bytes=").append(f.getBody().getNumAddresses())
             .append(" callers=").append(f.getSymbol().getReferenceCount()).append('\n');
            h.append("// calls:");
            for (Function c : f.getCalledFunctions(monitor)) h.append(' ').append(c.getEntryPoint());
            h.append('\n');
            try (PrintWriter w = new PrintWriter(new FileWriter(out))) {
                w.print(h);
                w.print(r.getDecompiledFunction().getC());
            }
            if (++done % 500 == 0) println("shard " + shard + ": " + done + " done, " + failed + " failed");
        }
        println("SHARD " + shard + " FINISHED done=" + done + " skipped=" + skipped + " failed=" + failed);
    }
}
