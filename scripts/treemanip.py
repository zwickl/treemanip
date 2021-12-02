#!/usr/bin/env python
import sys
import os
import re
import shlex
import subprocess
import argparse

if  sys.version_info[0] < 3:
    from itertools import izip_longest as zip_longest
else:
    from itertools import zip_longest

from random import sample
import dendropy

#for dendropy 4 compatability
try:
    from dendropy.error import DataError as DataParseError
except:
    from dendropy.utility.error import DataParseError

from dendropy.dataio.nexusreader  import NexusReader
from dendropy.dataio.tokenizer  import Tokenizer

def check_for_polytomies(tree):
    '''Check for polytomies by looking for nodes with > 3 neighbors.'''
    for node in tree.postorder_node_iter():
        if len(node.adjacent_nodes()) > 3:
            return True
        elif len(node.adjacent_nodes()) == 2:
            sys.stderr.write('Warning: tree appears to be rooted\n')
    return False


parser = argparse.ArgumentParser(description='Read trees from one or many treefiles in nexus or newick format, manipulate or filter, and write to a new treefile')

parser.add_argument('treefiles', nargs='*', default=[], help='nexus or newick treefile(s) to convert (omit for stdin)')

parser.add_argument('--ignore-read-errors', action='store_true', default=False, 
                    help='ignore treefiles that cannot be read properly (default False)')

parser.add_argument('-o', '--outfile', default=None, 
                    help='file to write output to (default is stdout)')

rootingArgs = parser.add_argument_group('ARGUMENTS FOR REORIENTING TREES')

mut_group1 = rootingArgs.add_mutually_exclusive_group()

mut_group1.add_argument('-op', '--outgroup-pattern', default=None,
                    help='regex pattern matching taxon label to use as outgroup (single taxon outgroup) NOTE: trees without a matching outgroup are not rerooted')

mut_group1.add_argument('-m', '--midpoint-root', action='store_true', default=False,
                    help='midpoint root the output trees')


formatArgs = parser.add_argument_group('ARGUMENTS FOR OUTPUT FORMAT')

formatArgs.add_argument('-n', '--nexus', action='store_true', default=False, 
                    help='output treefile in nexus rather than newick format (default False)')

formatArgs.add_argument('--suppress-branchlengths', action='store_true', default=False, 
                    help='strip branchlengths from output trees (default False)')

formatArgs.add_argument('--rooting-comment', action='store_true', default=None, 
                    help='include [&U] or [&R] to indicate rooting status before trees in newick or nexus format (default False in newick, True in nexus)')

formatArgs.add_argument('--retain-comments', action='store_true', default=False, 
                    help='output any comments (besides rooting) that might have appeared with a tree (default False)')

formatArgs.add_argument('--scale-by', default=None, type=float,
                    help='scale branchlengths by this value before tree output')

formatArgs.add_argument('--collapse-edges', default=None, type=float,
                    help='collapse all edges less than or equal to the specified length')


filterArgs = parser.add_argument_group('ARGUMENTS FOR TREE FILTERING/MANIPULATION')

mut_group2 = filterArgs.add_mutually_exclusive_group()

mut_group2.add_argument('-nb', '--no-bifurcating', action='store_true', default=False, 
                    help='omit bifurcating trees from output (default False)')

mut_group2.add_argument('-np', '--no-polytomies', action='store_true', default=False, 
                    help='omit polytomous trees from output (default False)')

mut_group2.add_argument('--make-bifurcating', action='store_true', default=False, 
                    help='randomly resolve polytomous nodes with zero-length branches, meaning that all trees will be output and will be bifurcating (default False)')

'''
Haven't implemented this yet
mut_group2.add_argument('--all-resolutions', action='store_true', default=False, 
                    help='return all bifurcating resolutions of a single polytomous input tree')
'''

mut_group3 = filterArgs.add_mutually_exclusive_group()

mut_group3.add_argument('--prune-to-common-taxa', action='store_true', default=False, 
                    help='prune all trees down to those taxa present in all of them (default False)')

mut_group3.add_argument('--only-all-taxa', action='store_true', default=False, 
                    help='only include those trees that contain the union of all taxa in any tree (default False)')


mut_group4 = filterArgs.add_mutually_exclusive_group()

mut_group4.add_argument('-p', '--prune-patterns', action='append', default=None, 
                    help='regex patterns for taxon names to strip from trees before output.  Single pattern per flag, but can appear multiple times')

mut_group4.add_argument('-f', '--prune-pattern-file', default=None, type=str,
                    help='read regex patterns from indicated file for taxon names to strip from trees before output')

mut_group4.add_argument('--prune-from-mrca', nargs=2, default=None, 
                    help='prune subtree defined by MRCA of two taxon labels')

mut_group4.add_argument('--retain-patterns', action='append', default=None, 
                    help='regex patterns for taxon names to maintain in tree - all non-matching taxa are pruned. Single pattern per flag, but can appear multiple times')

mut_group4.add_argument('--retain-pattern-file', default=None, type=str,
                    help='read regex patterns from indicated file for taxon names to retain in tree - all non-matching taxa are pruned')


filterArgs.add_argument('--verbatim', action='store_true', default=False, 
                    help='treat the --prune-patterns or patterns read from --pattern-file as exact taxon names rather than regex patterns')

filterArgs.add_argument('--max-trees', type=int, default=None,
                    help='only output the first --max-trees trees that match other filtering criteria')

filterArgs.add_argument('--subsample', type=int, default=None, 
                    help='subsample the specified number of trees from the total number that match other filtering criteria')


annotateArgs = parser.add_argument_group('ARGUMENTS FOR TREE ANNOTATION')

annotateArgs.add_argument('--annotate-taxa-file', default=None, type=str,
                    help='read a list of taxa from file, and add annotations to them in the output tree')

annotateArgs.add_argument('--annotate-string', default=None, type=str,
                    help='annotation string to attach to taxa listed in --annotate-taxa-file')


#privateArgs = parser.add_argument_group('PRIVATE FUNCTIONS (END USERS HAVE NO REASON TO USE THESE)')
#privateArgs.GUI_IGNORE = True
#privateArgs.add_argument('--output-seq-lengths', action='store_true', default=False, 
#                  help='(private) very specialized function to extract and output sequence lengths from tree filenames. Assumes only one tree per file!')


quiet = False


#if no arguments are passed, try to start the tkinter gui
tk_root = None
if len(sys.argv) == 1:
    try:

        if  sys.version_info[0] < 3:
            from Tkinter import *
        else:    
            from tk import *
        #try to use my tkarg package 
        try:
            from tkarg import ArgparseGui
        except ImportError:
            from tkinterutils import *
        from ttk import *
    except ImportError:
        sys.stderr.write('%s\n' % parser.format_help())
        sys.stderr.write('\nUnable to import GUI componenets.  Use command line options.\n\n'.upper())
        sys.exit()

    tk_root = Tk()
    tk_gui = ArgparseGui(parser, tk_root, width=1152, height=720)
    tk_gui.bring_to_front()

  
    #This will block until the window is destroyed by pressing Cancel or Done
    tk_root.wait_window(tk_gui.frame)
    if tk_gui.cancelled:
        sys.exit('cancelled ...')
    options = parser.parse_args(tk_gui.make_commandline_list())

else:
    options = parser.parse_args()

options.output_seq_lengths = False

intrees = dendropy.TreeList()
if not options.treefiles:
    sys.stderr.write('NOTE: reading trees from stdin\n')
    if hasattr(options, 'output_seq_lengths') and options.output_seq_lengths:
        sys.exit('ERROR: must pass filenames to output sequence lengths\n')
    trees = sys.stdin.read()
    #try two input formats
    #Think that there was some reason that I added preserve_underscores=True here, but it ended up causing more serious problems elsewhere
    try:
        #intrees.extend(dendropy.TreeList.get_from_string(trees, "nexus", case_sensitive_taxon_labels=True, preserve_underscores=True))
        intrees.extend(dendropy.TreeList.get_from_string(trees, "nexus", case_sensitive_taxon_labels=True))
    except DataParseError:
        #intrees.extend(dendropy.TreeList.get_from_string(trees, "newick", case_sensitive_taxon_labels=True, preserve_underscores=True))
        intrees.extend(dendropy.TreeList.get_from_string(trees, "newick", case_sensitive_taxon_labels=True))
    except (DataParseError, Tokenizer.UnexpectedEndOfStreamError, AttributeError) as e:
        if not quiet:
            sys.stderr.write('%s\n' % e.message)
            sys.exit('Could not read file %s in nexus or newick  format ...\n' % tf)

else:
    for tf in options.treefiles:
        #try two input formats
        try:
            #intrees.extend(dendropy.TreeList.get_from_path(tf, "nexus", case_sensitive_taxon_labels=True, preserve_underscores=True))
            intrees.extend(dendropy.TreeList.get_from_path(tf, "nexus", case_sensitive_taxon_labels=True))
        except DataParseError:
            #intrees.extend(dendropy.TreeList.get_from_path(tf, "newick", case_sensitive_taxon_labels=True, preserve_underscores=True))
            intrees.extend(dendropy.TreeList.get_from_path(tf, "newick", case_sensitive_taxon_labels=True))
        except (DataParseError, Tokenizer.UnexpectedEndOfStreamError, AttributeError) as e:
            if not quiet:
                sys.stderr.write('%s\n' % e.message)
                sys.exit('Could not read file %s in nexus or newick  format ...\n' % tf)
        '''
        except ValueError:
            sys.stderr.write('NOTE: ValueError reading from file %s, ' % tf)
            if options.ignore_read_errors:
                sys.stderr.write('ignoring file')
            else:
                sys.exit('exiting (use --ignore-read-errors to ignore this error)')
        except AttributeError:
            sys.stderr.write('NOTE: AttributeError reading from file %s, ' % tf)
            if options.ignore_read_errors:
                sys.stderr.write('ignoring file')
            else:
                sys.exit('exiting (use --ignore-read-errors to ignore this error)')

        '''

sys.stderr.write('read %d trees\n' % len(intrees))

if hasattr(options, 'output_seq_lengths') and options.output_seq_lengths:
    if len(intrees) != len(options.treefiles):
        sys.exit('ERROR: can only have one tree per file to output sequence lengths\n')
    treefiles = []

#treestr = '(O._barthii_AA:0.00157155,(((O._brachyantha_FF:0.10458481,(O._punctata_BB:0.00266559,O._minuta_BB:0.01210456):0.01556435):0.00268608,(O._officinalis_CC:0.10078888,O._minuta_CC:0.02347313):0.01668656):0.03394209,((O._sativaj_AA:0.01511099,O._rufipogon_AA:0.00251092):0.00401496,O._nivara_AA:0.002933):0.00296048):0.00068407,O._glaberrima_AA:1e-08);'
#intree = dendropy.Tree()
#intree.read_from_string(treestr, 'newick')

out = open(options.outfile, 'w') if options.outfile else sys.stdout
log = sys.stderr

outtrees = dendropy.TreeList()
ignoredCount = 0
outgroupIgnoredCount = 0
madeBifurcating = 0
#the treefiles here are only used for --output-seq-lengths mode, which requires one tree per
#file, and are otherwise ignored. If ignored there may be more trees than treefiles, hence the
#zip_longest
for intree, treefile in zip_longest(intrees, options.treefiles):
    hasPoly = check_for_polytomies(intree)
    if options.no_bifurcating and not hasPoly:
        ignoredCount += 1
    elif options.no_polytomies and hasPoly:
        ignoredCount += 1
    else:
        if options.make_bifurcating and hasPoly:
            intree.resolve_polytomies(update_splits=True)
            madeBifurcating += 1
        #prune taxa first with patterns, THEN look for an outgroup pattern.
        #outgroup pattern could be specified that matches something that has
        #already been deleted
        if options.prune_patterns or options.retain_patterns or options.prune_pattern_file or options.retain_pattern_file or options.annotate_taxa_file:
            if options.prune_patterns or options.prune_pattern_file:
                sys.stderr.write('pruning matching taxa ...\n')
                pruning = True
            else:
                sys.stderr.write('retaining matching taxa ...\n')
                pruning = False
            
            annotating =False 
            if options.annotate_taxa_file:
                annotating = True
                sys.stderr.write('annotating matching taxa with %s...\n' % options.annotate_string)
                
                with open(options.annotate_taxa_file, 'rb') as afile:
                    patterns = [ line.strip() for line in afile ]
           
            elif options.prune_pattern_file or options.retain_pattern_file:
                with open(options.prune_pattern_file or options.retain_pattern_file, 'rb') as pfile:
                    patterns = [ line.strip() for line in pfile ]
            else:
                patterns = options.prune_patterns or options.retain_patterns
            
            matches = set()
            
            if options.verbatim:
                #need to test what fastest string identity test is, think that this is pretty good
                #dangerous to do == because depends on identical strings being internally the same
                #object (which they generally are)
                compare = lambda x, y:x in y and y in x
            else:
                patterns = [ re.compile(patt) for patt in patterns ]
                compare = lambda comp_pat, label: comp_pat.search(label)

            for t in intree.taxon_namespace:
                for to_match in patterns:
                    if compare(to_match, t.label):
                        #sys.stdout.write('%s\n' % to_match)
                        matches.add(t)
                        break
                    elif compare(to_match, re.sub('_', ' ', t.label)):
                        matches.add(t)
                        break
                    elif compare(to_match, re.sub(' ', '_', t.label)):
                        matches.add(t)
                        break

            if annotating:
                key, val = options.annotate_string.split('=')
                for match in matches:
                    intree.find_node_for_taxon(match).annotations.add_new('%s'  % key, '%s' %  val)

            else:
                if pruning:
                    #print 'PRUNING', matches, intree.is_rooted, intree.is_unrooted
                    intree.prune_taxa(matches)
                else:
                    intree.retain_taxa(matches)

            #these are called on TreeLists - not sure if applicable here
            #intree.taxon_set = intree.infer_taxa()
            #intree.reindex_subcomponent_taxa()

        if options.outgroup_pattern is not None:
            outgroup = None
            leaves = intree.leaf_nodes()
            for l in leaves:
                #try replacing spaces with _ too
                if re.search(options.outgroup_pattern, l.taxon.label) is not None or re.search(options.outgroup_pattern, re.sub(' ', '_', l.taxon.label)) is not None:
                    if outgroup:
                        sys.exit('ERROR: outgroup pattern matched multiple times\n')
                    outgroup = l

            if outgroup is None:
                outgroupIgnoredCount += 1
                continue
            else:
                #if the tree was already rooted, this will remove that root node
                #outgroup rooting halves the branchlength of the chosen branch
                if outgroup.edge_length:
                    intree.reroot_at_edge(outgroup.edge, length1=outgroup.edge_length / 2.0, length2=outgroup.edge_length / 2.0, update_splits=False, delete_outdegree_one=True) 
                else:
                    intree.reroot_at_edge(outgroup.edge, update_splits=False, delete_outdegree_one=True) 
        
        elif options.midpoint_root:
            #intree.reroot_at_midpoint(update_splits=False, delete_outdegree_one=True) 
            intree.reroot_at_midpoint(update_bipartitions=False, suppress_unifurcations=True) 
        
        outtrees.append(intree)
        if options.output_seq_lengths:
            treefiles.append(treefile)

if options.prune_to_common_taxa:
    #remove all taxa that don't appear in all trees
    common_taxon_labels = set(l.taxon.label for l in outtrees[0].leaf_nodes())
    for tree in outtrees[1:]:
        common_taxon_labels &= set(l.taxon.label for l in tree.leaf_nodes())
    
    for tree in outtrees:
        tree.retain_taxa_with_labels(common_taxon_labels)
        #tree.taxon_set = tree.infer_taxa()

    if not common_taxon_labels:
        sys.exit('ERROR: no taxa found in all trees')

    log.write('pruning all trees to set of %d common taxa\n' % len(common_taxon_labels))

    outtrees.taxon_namespace = outtrees[0].taxon_namespace

elif options.prune_from_mrca:
    new_outtrees = dendropy.TreeList(taxon_namespace=outtrees.taxon_namespace)
    for tree in outtrees:
        try:
            mrca = tree.mrca(taxon_labels=options.prune_from_mrca)
        except KeyError as e:
            sys.exit('could not find specified MRCA taxa in tree: %s' % options.prune_from_mrca)
        if not mrca:
            sys.exit('Problem finding MRCA for %s and %s.' % (options.prune_from_mrca[0], options.prune_from_mrca[1]))
        #subtree_tips = [ it.taxon for it in mrca.leaf_iter() ]
        #tree.retain_taxa(subtree_tips)
        new_outtrees.append(dendropy.Tree(seed_node=mrca))
    outtrees = new_outtrees

elif options.only_all_taxa:
    #only keep trees that contain all taxa observed in any tree
    all_taxon_labels = set()
    for tree in outtrees:
        all_taxon_labels |= set(l.taxon.label for l in tree.leaf_nodes())

    finalSet = dendropy.TreeList()
    for tree in outtrees:
        if set(l.taxon.label for l in tree.leaf_nodes()) == all_taxon_labels:
            finalSet.append(tree)

    if len(finalSet) == 0:
        sys.exit('No trees contain all taxa! ("%s")' % '", "'.join(all_taxon_labels))
    log.write('ignoring %d trees without all taxa\n' % (len(outtrees) - len(finalSet)))

    outtrees = finalSet

if ignoredCount > 0:
    log.write('ignored %d trees\n' % ignoredCount)
if outgroupIgnoredCount > 0:
    log.write('ignored %d trees because of missing outgroup matching \'%s\'\n' % (outgroupIgnoredCount, options.outgroup_pattern))
if madeBifurcating > 0:
    log.write('%d polytomous trees arbitrarily resolved\n' % madeBifurcating)

if outtrees:
    if options.max_trees:
        if options.subsample:
            sys.exit('can\'t specify both --max-trees and --subsample')
        outtrees[options.max_trees:] = []

    if options.subsample:
        outtrees = dendropy.TreeList(sample(outtrees, options.subsample))
        
    if options.collapse_edges:
        log.write('collaping edges with length <= %g\n' % options.collapse_edges)
        #collapse_unweighted_edges should do this, but there is a bug in the version I'm currently using
        #so, this is a local reimplementation of a Tree function
        for t in outtrees:
            for e in t.postorder_edge_iter():
                if not e.is_terminal():
                    if e.length <= options.collapse_edges:
                        e.collapse()

    if options.scale_by:
        log.write('rescaling branch lengths by %f\n' % options.scale_by)
        for t in outtrees:
            t.scale_edges(options.scale_by)
    
    log.write('writing %d trees\n' % len(outtrees))
    
    if options.rooting_comment is None:
        if options.nexus:
            supress_root_comment = False
        else:
            supress_root_comment = True
    else:
        supress_root_comment = not options.rooting_comment

    if options.nexus:
        if not options.retain_comments:
            for tree in outtrees:
                tree.comments = []
        #outtrees.write(file=out, schema="nexus", suppress_edge_lengths=options.suppress_branchlengths, suppress_rooting=supress_root_comment, simple=True)
        outtrees.write(file=out, schema="nexus", suppress_edge_lengths=options.suppress_branchlengths, suppress_rooting=supress_root_comment)
    else:
        outtrees.write(file=out, schema="newick", suppress_edge_lengths=options.suppress_branchlengths, suppress_rooting=supress_root_comment)

    if options.output_seq_lengths:
        length_filename = 'seqlens.' + options.outfile if options.outfile else 'seqlens'
        with open(length_filename, 'w') as outlengths:
            for treef in treefiles:
                match = re.search('([0-9]+)C', treef)
                if not match:
                    sys.exit('failed to parse seq len out of %s\n' % treef)
                slen = int(match.group(1))
                outlengths.write('Sequence length = %d;\n' % slen)
else:
    log.write('no trees to output?\n')

