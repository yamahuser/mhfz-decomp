// Applies analysis/merged_names.csv (addr,name,confidence,tier,subsystem,purpose) to the open program:
// renames functions (name_<addr>, so every name is unique and greppable) and adds the purpose as a plate comment.
// Run headless on a COPY of the project:
//   analyzeHeadless <projdir> <proj> -process mhfo-hd.dll -noanalysis -scriptPath ghidra\scripts -postScript ApplyNames.java <csv> <minConfidence>
// Only renames functions that still have a default name (FUN_*); existing names (e.g. CRT symbols) are kept.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.CodeUnit;
import ghidra.program.model.symbol.SourceType;
import java.io.BufferedReader;
import java.io.FileReader;
import java.util.ArrayList;
import java.util.List;

public class ApplyNames extends GhidraScript {
    private static List<String> parseCsv(String line) {
        List<String> out = new ArrayList<>();
        StringBuilder cur = new StringBuilder();
        boolean q = false;
        for (int i = 0; i < line.length(); i++) {
            char c = line.charAt(i);
            if (q) {
                if (c == '"') { if (i + 1 < line.length() && line.charAt(i + 1) == '"') { cur.append('"'); i++; } else q = false; }
                else cur.append(c);
            } else if (c == '"') q = true;
            else if (c == ',') { out.add(cur.toString()); cur.setLength(0); }
            else cur.append(c);
        }
        out.add(cur.toString());
        return out;
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String csv = args.length > 0 ? args[0] : "C:\\Users\\Ayman\\mhfz-60fps\\analysis\\merged_names.csv";
        double minConf = args.length > 1 ? Double.parseDouble(args[1]) : 0.45;
        int renamed = 0, skippedExisting = 0, missing = 0, lowConf = 0, failed = 0;
        try (BufferedReader br = new BufferedReader(new FileReader(csv))) {
            String line = br.readLine(); // header
            while ((line = br.readLine()) != null) {
                List<String> f = parseCsv(line);
                if (f.size() < 3) continue;
                String addrHex = f.get(0).trim();
                String name = f.get(1).trim().replaceAll("[^A-Za-z0-9_]", "_");
                double conf = 0;
                try { conf = Double.parseDouble(f.get(2)); } catch (Exception e) { }
                if (conf < minConf || name.isEmpty()) { lowConf++; continue; }
                Address a = toAddr("0x" + addrHex);
                Function fn = a == null ? null : getFunctionAt(a);
                if (fn == null) { missing++; continue; }
                if (!fn.getName().startsWith("FUN_")) { skippedExisting++; continue; }
                try {
                    fn.setName(name + "_" + addrHex, SourceType.USER_DEFINED);
                    String purpose = f.size() > 5 ? f.get(5) : "";
                    String tier = f.size() > 3 ? f.get(3) : "";
                    if (!purpose.isEmpty()) {
                        setPlateComment(a, "[" + tier + " conf " + f.get(2) + "] " + purpose);
                    }
                    renamed++;
                } catch (Exception e) { failed++; }
            }
        }
        println("ApplyNames: renamed=" + renamed + " keptExisting=" + skippedExisting + " noFunction=" + missing
                + " belowConf=" + lowConf + " failed=" + failed);
    }
}
