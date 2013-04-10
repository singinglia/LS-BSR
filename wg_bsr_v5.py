#!/usr/bin/env python

"""Calculate the BSR value for all predicted ORFs
in a set of genomes in fasta format.  V3 - replaced
transeq with BioPython.  V4 - changed to true BSR
test.  V5 - fixed bug in how BSR was calculated.
V6 - changed gene caller from Glimmer to Prodigal"""

import Bio
from Bio import SeqIO
import sys
import os
import glob
import optparse
import subprocess
import shlex
from subprocess import call
from Bio.SeqRecord import SeqRecord
from igs.utils import functional as func
from igs.utils import logging
from igs.threading import functional as p_func
import errno

def get_seq_name(in_fasta):
    """used for renaming the sequences"""
    return os.path.basename(in_fasta)

def predict_genes(directory, processors):
    """simple gene prediction using Prodigal in order
    to find coding regions from a genome sequence"""    
    os.chdir("%s/joined" % directory)
    curr_dir=os.getcwd()
    files = os.listdir(curr_dir)
    files_and_temp_names = [(str(idx), os.path.join(curr_dir, f))
                            for idx, f in enumerate(files)]
                         
    def _perform_workflow(data):
        tn, f = data
        names = get_seq_name(f)
        reduced = names.replace('.fasta.new','')
        subprocess.check_call("prodigal -i %s -d %s_genes.seqs -a %s_genes.pep > /dev/null 2>&1" % (f, reduced, reduced), shell=True)
        
    results = set(p_func.pmap(_perform_workflow,
                              files_and_temp_names,
                              num_workers=processors))

def uclust_sort():
    """sort with Usearch. Updated to V6"""
    cmd = ["usearch6", 
           "-sortbylength", "all_gene_seqs.out",
           "-output", "all_sorted.txt"]
    subprocess.check_call(cmd)

def uclust_cluster(id):
    """cluster with Uclust.  Updated to V6"""
    cmd = ["usearch6",
           "-cluster_fast", "all_sorted.txt",
           "-id", str(id),
           "-uc", "results.uc",
           "-centroids", "consensus.fasta"]
    subprocess.check_call(cmd)

def translate_consensus(consensus):
    """translate nucleotide into peptide with BioPython"""
    infile = open(consensus, "rU")
    output_handle = open("tmp.pep", "w")
    for record in SeqIO.parse(infile, "fasta"):
        print >> output_handle, ">"+record.id
        print >> output_handle, record.seq.translate(to_stop=True)

def filter_seqs(input_pep):
    """filter out short sequences from a multifasta.
    Will hopefully speed up the process without losing
    important information"""
    long_sequences = [ ]
    infile = open(input_pep, "rU")
    outfile = open("consensus.pep", "w")
    for record in SeqIO.parse(infile, "fasta"):
        if len(record.seq) > int(50):
            long_sequences.append(record)
    SeqIO.write(long_sequences, outfile, "fasta")
    outfile.close()

def blast_against_each_genome(directory, processors, filter):
    """BLAST all peptides against each genome"""
    curr_dir=os.getcwd()
    files = os.listdir(curr_dir)
    files_and_temp_names = [(str(idx), os.path.join(curr_dir, f))
                            for idx, f in enumerate(files)]
    def _perform_workflow(data):
	tn, f = data
        names = get_seq_name(f)
        if ".fasta.new" in f:
            subprocess.check_call("formatdb -i %s -p F > /dev/null 2>&1" % f, shell=True)
        if ".fasta.new" in f:
            cmd = ["blastall",
                   "-p", "tblastn",
                   "-i", "consensus.pep",
                   "-d", f,
                   "-a", str(processors),
                   "-b", "1",
                   "-v", "1",
                   "-e", "0.1",
                   "-m", "8",
                   "-F", str(filter),
                   "-o", "%s_blast.out" % f]
            subprocess.check_call(cmd)
            
    results = set(p_func.pmap(_perform_workflow,
                              files_and_temp_names,
                              num_workers=processors))

def parse_blast_report(directory):
    """parse out only the name and bit score from the blast report"""
    curr_dir=os.getcwd()
    for infile in glob.glob(os.path.join(curr_dir, "*_blast.out")):
        names = get_seq_name(infile)
        ref = open(infile, "rU")
        data = ref.readlines()
        outfile = open("%s.filtered" % names, "w")
        for line in data:
            fields = line.split("\t")
            print >> outfile, fields[0]+"\t"+fields[11],
            
def get_unique_lines(directory):
    """only return the top hit for each query"""
    curr_dir=os.getcwd()
    for infile in glob.glob(os.path.join(curr_dir, "*.filtered")):
        names = get_seq_name(infile)
        outfile = open("%s.filtered.unique" % names, "w")
        d = {}
        input = file(infile)
        for line in input:
            unique = line.split("\t",1)[0]
            if unique not in d:
                d[unique] = 1
                print >> outfile,line,
    
def make_table(directory):
    """make the BSR matrix table"""
    clusters=[ ]
    curr_dir=os.getcwd()
    """I only use this loop to grab names...combine with next loop?
       I need the nr values before the next loop"""
    for infile in glob.glob(os.path.join(curr_dir, "*.filtered.unique")):
        file=open(infile, "rU")
        for line in file:
		fields=line.split()
                if fields[0] not in clusters:
                    clusters.append(fields[0])
    """de-replicate the clusters"""
    nr=[x for i, x in enumerate(clusters) if x not in clusters[i+1:]]
    names = [ ]
    for infile in glob.glob(os.path.join(curr_dir, "*.filtered.unique")):
        """get the name of each of the files to be iterated"""
        name=[ ]
        out=get_seq_name(infile)
        name.append(out)
        reduced=[ ]
        """remove the junk at the end of the file"""
	for x in name:reduced.append(x.replace('.fasta.new_blast.out.filtered.filtered.unique',''))
        names.append(reduced)
        dict={}
        file=open(infile, "rU")
        tmpfile=open("tmp.txt", "w")
        """make a dictionary of all clusters and values"""
        for line in file:
            fields=line.split()
            dict.update({fields[0]:fields[1]})
        cluster_names={}
        """add in values, including any potentially missing ones"""
        for k,v in dict.iteritems():
            if k in nr: cluster_names.update({k:v})
        for x in nr:
            if x not in dict.keys():cluster_names.update({x:0})
        """need to write a blank space"""
        for x in reduced: open("%s.tmp.matrix" % x, 'a').write('%s\n' % x)
        """sort keys to get the same order between samples"""
        for key in sorted(cluster_names.iterkeys()):
            for x in reduced:
                open("%s.tmp.matrix" % x, 'a').write("%s\n" % cluster_names[key])
    names_out = open("names.txt", "w")
    for x in names: print >> names_out, "".join(x)
    nr_sorted=sorted(nr)
    open("ref.list", "a").write("\n")
    for x in nr_sorted:
        open("ref.list", "a").write("%s\n" % x)

def divide_values(file, ref_scores):
    """divide each BSR value in a row by that row's maximum value"""
    infile = open(file, "rU")
    firstLine = infile.readline()
    FL_F=firstLine.split()
    outfile = open("BSR_matrix_values.txt", "a")
    print >> outfile, '\t'.join([str(item) for item in FL_F])
    for line in infile:
        fields=line.split()
        all_fields=list(fields)
        fields=map(float, fields[1:])
        values= [ ]
        """v7 - added in exception to address bug"""
	for x in fields:
            try:
                values.append(float(x)/float(ref_scores.get(all_fields[0])))
            except:
                values.append(float(x)/float("1000"))
        sort_values=['%.2f' % elem for elem in values]
        print >> outfile, '\t'.join([str(item) for item in sort_values])

def blast_against_self(genes_nt, genes_pep, output, filter):
    cmd = ["blastall",
           "-p", "tblastn",
           "-i", genes_pep,
           "-d", genes_nt,
           "-a", "2",
           #"-b", "1",
           #"-v", "1",
           "-e", "0.1",
           "-m", "8",
           "-F", str(filter),
           "-o", output]
    subprocess.check_call(cmd)

def parse_self_blast(blast_out):
    my_dict={}
    for line in open(blast_out):
        fields=line.split()
        str1=fields[0]
        str2=fields[11]
        my_dict.update({str1:str2})
    return my_dict

def main(directory, id, filter, processors):
    try:
     	os.makedirs('%s/joined' % directory)
    except OSError, e:
     	if e.errno != errno.EEXIST:
            raise
    for infile in glob.glob(os.path.join(directory, '*.fasta')):
        name=get_seq_name(infile)
        os.system("cp %s %s/joined/%s.new" % (infile,directory,name))
    logging.logPrint("predicting genes with Prodigal")
    predict_genes(directory, processors)
    logging.logPrint("Prodigal done")
    os.system("cat *genes.seqs > all_gene_seqs.out")
    uclust_sort()
    uclust_cluster(id)
    translate_consensus("consensus.fasta")
    filter_seqs("tmp.pep")
    subprocess.check_call("formatdb -i consensus.fasta -p F", shell=True)
    blast_against_self("consensus.fasta", "consensus.pep", "tmp_blast.out", filter)
    subprocess.check_call("sort -u -k 1,1 tmp_blast.out > self_blast.out", shell=True)
    ref_scores=parse_self_blast("self_blast.out")
    subprocess.check_call("rm tmp_blast.out self_blast.out", shell=True)
    logging.logPrint("starting BLAST")
    blast_against_each_genome(directory, processors, filter)
    logging.logPrint("BLAST done")
    parse_blast_report(directory)
    get_unique_lines(directory)
    make_table(directory)
    subprocess.check_call("paste ref.list *.matrix > bsr_matrix", shell=True)
    divide_values("bsr_matrix", ref_scores)
    subprocess.check_call("paste ref.list BSR_matrix_values.txt > ../bsr_matrix_values.txt", shell=True)
    subprocess.check_call("cp names.txt consensus.pep ..", shell=True)
    logging.logPrint("all Done")
    #ap=os.path.abspath("%s"+"/" % directory)
    #os.system("rm -rf %sjoined" % ap)
    
if __name__ == "__main__":
    usage="usage: %prog [options]"
    parser = optparse.OptionParser(usage=usage)
    parser.add_option("-d", "--directory", dest="directory",
                      help="/path/to/fasta_directory [REQUIRED]",
                      action="store", type="string")
    parser.add_option("-i", "--identity", dest="id",
                      help="clustering id for USEARCH (0.0-1.0)",
                      default="0.9", type="float")
    parser.add_option("-f", "--filter", dest="filter",
                      help="to use blast filtering or not",
                      default="F", type="string")
    parser.add_option("-p", "--parallel_workers", dest="processors",
                      help="How much work to do in parallel, defaults to 2, should number of CPUs your machine has",
                      action="store", type="int")
    options, args = parser.parse_args()
    
    mandatories = ["directory", "processors"]
    for m in mandatories:
        if not getattr(options, m, None):
            print "\nMust provide %s.\n" %m
            parser.print_help()
            exit(-1)

    main(options.directory, options.id, options.filter, options.processors)

