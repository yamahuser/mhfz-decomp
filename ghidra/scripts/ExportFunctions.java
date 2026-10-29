// Export all functions (addr,size,name,callers) to CSV and print summary stats.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.util.*;

public class ExportFunctions extends GhidraScript {
    @Override
    public void run() throws Exception {
        String out = "C:\\Users\\Ayman\\mhfz-60fps\\ghidra\\functions.csv";
        int n = 0, named = 0;
        long bytes = 0;
        try (PrintWriter w = new PrintWriter(new FileWriter(out))) {
            w.println("addr,size,name,callers");
            FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
            while (it.hasNext()) {
                Function f = it.next();
                long size = f.getBody().getNumAddresses();
                int callers = f.getSymbol().getReferenceCount();
                String name = f.getName();
                if (!name.startsWith("FUN_")) named++;
                w.printf("%s,%d,%s,%d%n", f.getEntryPoint(), size, name, callers);
                n++;
                bytes += size;
            }
        }
        println("FUNCTIONS=" + n + " NAMED=" + named + " BYTES=" + bytes);

        // C++ class names recovered from RTTI / namespaces
        Set<String> classes = new TreeSet<>();
        SymbolIterator si = currentProgram.getSymbolTable().getAllSymbols(true);
        while (si.hasNext()) {
            Symbol s = si.next();
            Namespace ns = s.getParentNamespace();
            if (ns != null && ns.getSymbol().getSymbolType() == SymbolType.CLASS)
                classes.add(ns.getName(true));
        }
        println("CLASSES=" + classes.size());
        try (PrintWriter w = new PrintWriter(new FileWriter("C:\\Users\\Ayman\\mhfz-60fps\\ghidra\\classes.txt"))) {
            for (String c : classes) w.println(c);
        }
    }
}
