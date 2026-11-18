import React from "react";
import {render,screen,cleanup} from "@testing-library/react";
import {afterEach, it} from "node:test";
import {expect} from "chai";
import {ReferralNetwork} from "./referral-network";
afterEach(cleanup);
it("shows anonymous network and explicit truncation",()=>{
 render(<ReferralNetwork data={{nodes:[{id:"root",parent:null,level:0},{id:"child",parent:"root",level:1}],level_counts:[{level:1,count:1}],truncated:true}}/>);
 expect(screen.getByRole("img",{name:"Обезличенный граф реферальной сети"})).to.be.ok;
 expect(screen.getByText("Участник 1")).to.be.ok;
 expect(screen.getByText(/сеть продолжается/)).to.be.ok;
});
it("shows root without inventing invitees",()=>{
 render(<ReferralNetwork data={{nodes:[{id:"root",parent:null,level:0}],level_counts:[{level:1,count:0}],truncated:false}}/>);
 expect(screen.getByText("Вы")).to.be.ok;
 expect(screen.queryByText(/^Участник \d+$/)).to.be.null;
 expect(screen.queryByText(/сеть продолжается/)).to.be.null;
});
