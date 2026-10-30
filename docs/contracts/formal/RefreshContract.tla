------------------------ MODULE RefreshContract ------------------------
EXTENDS Naturals, FiniteSets

CONSTANT Files
VARIABLES sources, unchanged, changed, includeEdges, importEdges,
          ready, clear, index

Inputs == <<sources, unchanged, changed, includeEdges, importEdges>>
vars == <<Inputs, ready, clear, index>>

(* Positive-length reachability, including the seed only on a cycle. *)
RECURSIVE Reach(_, _, _)
Reach(edges, seeds, remaining) ==
    IF remaining = 0 THEN {}
    ELSE LET next == {v \in Files : \E u \in seeds : <<u, v>> \in edges}
         IN next \cup Reach(edges, next, remaining - 1)

(* Match PersistentStorage: closure of each relation, then union. *)
Referenced(seeds) ==
    Reach(includeEdges, seeds, Cardinality(Files)) \cup
    Reach(importEdges, seeds, Cardinality(Files))

Affected == changed \cup
    {f \in Files : \E c \in changed : c \in Referenced({f})}
RetainedSources == sources \ Affected

(* Relational, per-file specification; no iteration order or storage IDs. *)
ExpectedClear == {f \in Files :
    f \in Affected \/
    (f \in Referenced(Affected) /\
     f \notin RetainedSources /\ f \notin Referenced(RetainedSources))}
ExpectedIndex == {f \in sources : f \in ExpectedClear \/ f \notin unchanged}

InputType ==
    /\ sources \subseteq Files
    /\ unchanged \subseteq Files
    /\ changed \subseteq Files
    /\ unchanged \cap changed = {}
    /\ includeEdges \subseteq Files \X Files
    /\ importEdges \subseteq Files \X Files

Init == /\ InputType
        /\ ready = FALSE
        /\ clear = {}
        /\ index = {}

Publish == /\ ~ready
           /\ ready' = TRUE
           /\ clear' = ExpectedClear
           /\ index' = ExpectedIndex
           /\ UNCHANGED Inputs

Spec == Init /\ [][Publish]_vars
=============================================================================
