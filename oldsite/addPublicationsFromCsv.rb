require 'bibtex';


def formatAuthors(authstring)
  authors = authstring.split(" and ")
  newauthors = Array.new
  authors.each {|auth|
    if(auth == "others")
      newauthors.push("<em>et al.</em>")
    elsif (auth == "Network, The Cancer Genome Atlas Research")
      newauthors.push("The Cancer Genome Atlas Research Network")
    else
      names = auth.strip.split(/,\s+|\s+/)
      newstring = names[0].strip + " " #last name
      for i in 1..(names.length-1) #rest of names, use initial
        newstring = newstring + names[i][0].upcase
      end

      #handle co-first authorship
      if(auth=~/\*$/)
        newstring=newstring + "*"
      end
      
      if newstring =~ /Miller CA?(\*?)/
        newstring = "<strong>Miller CA#{$1}</strong>"
      end


      newauthors.push(newstring)
    end
  }
  return newauthors.join(", ")
end


def capitalizeEach(mystring)
  arr = mystring.split(/\s+/)
  newarr = Array.new
  arr.each{|a|
    newarr.push(a.capitalize)
  }
  return newarr.join(" ")
end

def writePubs
  pubEntries = Array.new

  b = BibTeX.open('./citations.bib')
  b.each {|article|
    entry = ""
    #puts article.inspect
    entry =  '<li class="pub">' + '<a href="' + article.url + '">' + article.title + '</a><br />' + "\n"
    entry = entry + '<span class="pubdetails">'

        # puts article.authors
    entry = entry + formatAuthors(article.authors) + ". "
    unless (article.journal).nil?
      entry = entry + capitalizeEach(article.journal)
      entry.gsub!("Plos","PLoS")
      entry.gsub!("Bmc","BMC")
    end

    entry = entry + ". " + article.year
    entry = entry + ". " + article.doi
    entry = entry + '</span>' + "\n"
    entry = entry + '</li>' + "\n"
    pubEntries.push(entry)
  }

  #print them in reverse chron order
  pubEntries.reverse.each{|pub|
    puts pub
  }
end


f = File.open("index.nopubs", "r")
f.each_line do |line|
  if(line =~ /BIB GOES HERE/)
    writePubs()
  else
    puts line
  end
end
f.close

