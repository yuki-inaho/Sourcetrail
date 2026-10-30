-------------------------- MODULE RefreshPlan --------------------------
EXTENDS Naturals, FiniteSets

CONSTANTS Files, IncludeEdgeBound, ImportEdgeBound, PreserveShared
VARIABLES sources, unchanged, changed, includeEdges, importEdges,
          phase, affected, retained, clear, index

Inputs == <<sources, unchanged, changed, includeEdges, importEdges>>
vars == <<Inputs, phase, affected, retained, clear, index>>

Edges == {e \in Files \X Files : e[1] # e[2]}
BoundedGraphs(bound) == {g \in SUBSET Edges : Cardinality(g) <= bound}

RECURSIVE Reach(_, _, _)
Reach(edges, seeds, remaining) ==
    IF remaining = 0 THEN {}
    ELSE LET next == {v \in Files : \E u \in seeds : <<u, v>> \in edges}
         IN next \cup Reach(edges, next, remaining - 1)

Reverse(edges) == {<<e[2], e[1]>> : e \in edges}
Referenced(seeds) ==
    Reach(includeEdges, seeds, Cardinality(Files)) \cup
    Reach(importEdges, seeds, Cardinality(Files))
Referencing(seeds) ==
    Reach(Reverse(includeEdges), seeds, Cardinality(Files)) \cup
    Reach(Reverse(importEdges), seeds, Cardinality(Files))

Init ==
    /\ includeEdges \in BoundedGraphs(IncludeEdgeBound)
    /\ importEdges \in BoundedGraphs(ImportEdgeBound)
    /\ sources \in SUBSET Files
    /\ changed \in SUBSET Files
    /\ unchanged \in SUBSET (Files \ changed)
    /\ phase = "initial"
    /\ affected = {}
    /\ retained = {}
    /\ clear = {}
    /\ index = {}

FindAffected ==
    /\ phase = "initial"
    /\ affected' = changed \cup Referencing(changed)
    /\ phase' = "affected"
    /\ UNCHANGED <<Inputs, retained, clear, index>>

RetainSources ==
    /\ phase = "affected"
    /\ retained' = sources \ affected
    /\ phase' = "retained"
    /\ UNCHANGED <<Inputs, affected, clear, index>>

PlanClear ==
    /\ phase = "retained"
    /\ clear' = affected \cup
        (IF PreserveShared
         THEN Referenced(affected) \ (Referenced(retained) \cup retained)
         ELSE Referenced(affected))
    /\ phase' = "clear"
    /\ UNCHANGED <<Inputs, affected, retained, index>>

PlanIndex ==
    /\ phase = "clear"
    /\ index' = sources \cap (clear \cup (Files \ unchanged))
    /\ phase' = "done"
    /\ UNCHANGED <<Inputs, affected, retained, clear>>

Finish == /\ phase = "done" /\ UNCHANGED vars
Next == FindAffected \/ RetainSources \/ PlanClear \/ PlanIndex \/ Finish
Spec == Init /\ [][Next]_vars

(* A focused counterexample: two sources share a dependency; one changes. *)
MutantInit ==
    /\ Init
    /\ Cardinality(sources) = 2
    /\ Cardinality(changed) = 1
    /\ changed \subseteq sources
    /\ unchanged = sources \ changed
    /\ includeEdges = sources \X (Files \ sources)
    /\ importEdges = {}
MutantSpec == MutantInit /\ [][Next]_vars

(* Intermediate computations are invisible to callers: stuttering mapping. *)
Reference == INSTANCE RefreshContract
    WITH ready <- (phase = "done"),
         clear <- (IF phase = "done" THEN clear ELSE {}),
         index <- (IF phase = "done" THEN index ELSE {})

TypeInvariant ==
    /\ Reference!InputType
    /\ phase \in {"initial", "affected", "retained", "clear", "done"}
    /\ affected \subseteq Files
    /\ retained \subseteq Files
    /\ clear \subseteq Files
    /\ index \subseteq Files

ResultMatchesContract == phase = "done" =>
    /\ clear = Reference!ExpectedClear
    /\ index = Reference!ExpectedIndex
SharedDependenciesPreserved == phase = "done" =>
    (clear \ affected) \cap (retained \cup Referenced(retained)) = {}
ChangedFilesIncluded == phase = "done" => changed \subseteq clear
IndexSelectionComplete == phase = "done" =>
    /\ index \subseteq sources
    /\ (sources \ unchanged) \subseteq index
    /\ (sources \cap clear) \subseteq index
    /\ index \subseteq (sources \ unchanged) \cup clear
Refinement == Reference!Spec
=============================================================================
